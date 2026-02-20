import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Secure Ledger")

# Initialize Session State
if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []

# --- 2. SECURE CONNECTION ---
try:
    # This now uses the 'service_account' credentials from your secrets
    conn = st.connection("gsheets", type=GSheetsConnection)
    st.sidebar.success("🔒 Secure Connection Active")
except Exception as e:
    st.sidebar.error(f"Connection Error: {e}")
    conn = None

# --- 3. LOGIC ---
def get_score(h):
    s = 0
    form = str(h.get('form', ''))
    if form.endswith('1'): s += 15
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict) and float(t_stats.get('percent', 0)) > 15:
        s += 10
    return s

def get_best_odds(runner):
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list):
        prices = [float(e.get('decimal')) for e in odds_list if e.get('decimal') and e.get('decimal') not in ['-', 'SP', 'None']]
        if prices: return max(prices)
    return 0.0

# --- 4. INTERFACE ---
if st.button('🚀 Run Analysis'):
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
    races = r.json().get('racecards', [])
    
    st.session_state.value_horses = []
    if races:
        for race in races:
            for r_data in race.get('runners', []):
                o, s = get_best_odds(r_data), get_score(r_data)
                if s >= 20 and o >= 5.0:
                    st.session_state.value_horses.append({
                        "Date": datetime.now().strftime("%Y-%m-%d"),
                        "Horse": r_data.get('horse'),
                        "Course": race.get('course'),
                        "Odds": o,
                        "Score": s,
                        "Result": "Pending",
                        "P/L": 0.0
                    })

if st.session_state.value_horses:
    st.markdown("### 🏆 Top Value Bets")
    for h in st.session_state.value_horses[:3]:
        st.info(f"**{h['Horse']}** | Score: {h['Score']} | Odds: {int(h['Odds']-1)}/1")

    if st.button("📤 LOG SELECTIONS"):
        if conn:
            # Read existing
            existing = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            # Add new
            new_data = pd.DataFrame(st.session_state.value_horses)
            updated = pd.concat([existing, new_data[~new_data['Horse'].isin(existing['Horse'])]], ignore_index=True)
            # Write back
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Success! Data logged securely.")
            st.balloons()
