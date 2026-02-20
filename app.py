import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & SECRETS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Ledger Edition")

# Initialize Session State so results stay visible after clicking 'Log'
if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 2. THE SECURE CONNECTION ---
try:
    # Uses the [connections.gsheets] info you just fixed!
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Secure API Linked")
except Exception as e:
    st.sidebar.error(f"❌ Connection Error: {str(e)}")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            return conn.read(spreadsheet=GSHEET_URL, ttl=0)
        except:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Odds", "Score", "Result", "P/L"])

# --- 3. ODDS & SCORING ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and sp_val not in ['-', '', 'N/A', 'None']:
        try: return float(sp_val)
        except: pass
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list):
        prices = [float(e.get('decimal')) for e in odds_list if e.get('decimal') and e.get('decimal') not in ['-', 'SP', 'None']]
        if prices: return max(prices)
    return 0.0

def get_score(h):
    s = 0
    form = str(h.get('form', ''))
    if form.endswith('1'): s += 15
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            win_pc = float(t_stats.get('percent', 0))
            if win_pc > 20: s += 15
            elif win_pc > 10: s += 5
        except: pass
    return s

# --- 4. MAIN INTERFACE ---
st.sidebar.header("⚙️ Controls")
min_score = st.sidebar.slider("Minimum Value Score", 0, 50, 20, 5)

if st.sidebar.button("🔄 Reconcile Results"):
    ledger = load_ledger()
    if not ledger.empty and "Pending" in ledger['Result'].values:
        with st.sidebar:
            st.info("Checking for winners...")
            # API logic for results would go here
            st.warning("Feature: Result checking in progress...")

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing today's value..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        races = r.json().get('racecards', [])
        
        st.session_state.all_races = races
        st.session_state.value_horses = []
        
        if races:
            for race in races:
                for r_data in race.get('runners', []):
                    odds = get_best_odds(r_data)
                    score = get_score(r_data)
                    if score >= min_score and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'),
                            "Course": race.get('course'),
                            "Odds": odds,
                            "Score": score,
                            "Result": "Pending",
                            "P/L": 0.0
                        })

# SHOW TOP BETS
if st.session_state.value_horses:
    st.markdown("### 🏆 Top Daily Value Bets")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            st.success(f"### {h['Horse']}\n**{int(h['Odds']-1)}/1** \nScore: {h['Score']}")

    st.markdown("---")
    if st.button("📤 LOG ALL VALUE BETS TO GOOGLE SHEETS"):
        if conn:
            try:
                ledger = load_ledger()
                new_data = pd.DataFrame(st.session_state.value_horses)
                # Avoid logging the same horse twice
                filtered = new_data[~new_data['Horse'].isin(ledger['Horse'])]
                
                if not filtered.empty:
                    updated_df = pd.concat([ledger, filtered], ignore_index=True)
                    conn.update(spreadsheet=GSHEET_URL, data=updated_df)
                    st.balloons()
                    st.success(f"Successfully logged {len(filtered)} bets!")
                else:
                    st.info("These horses are already in your ledger.")
            except Exception as e:
                st.error(f"Logging Failed: {e}")

# FULL BREAKDOWN
if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'),
                "Score": get_score(r),
                "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP",
                "Value": "💎 YES" if (get_score(r) >= min_score and get_best_odds(r) >= 5.0) else ""
            } for r in race.get('runners', [])]))
