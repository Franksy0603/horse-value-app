import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# Safety check for the Google Sheets library
try:
    from streamlit_gsheets import GSheetsConnection
    HAS_GSHEETS = True
except ImportError:
    HAS_GSHEETS = False

# --- 1. SETTINGS & SECRETS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Google Sheets Ledger")

# --- 2. SIDEBAR CONTROLS & LEDGER ---
st.sidebar.header("⚙️ Controls")

# RESTORED: The Score Slider
min_score = st.sidebar.slider("Minimum Value Score", min_value=0, max_value=50, value=20, step=5)
st.sidebar.caption(f"Showing horses with score ≥ {min_score}")

st.sidebar.markdown("---")
st.sidebar.header("📊 Performance Ledger")

# Establish Google Sheets Connection
conn = None
if HAS_GSHEETS and GSHEET_URL:
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
    except:
        st.sidebar.warning("⚠️ Sheet Connection Failed")

def load_ledger():
    if conn and GSHEET_URL:
        try:
            return conn.read(spreadsheet=GSHEET_URL, ttl=0)
        except:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Odds", "Score", "Result", "P/L"])

if st.sidebar.button("🔄 Reconcile Results"):
    ledger = load_ledger()
    if not ledger.empty and "Pending" in ledger['Result'].values:
        with st.sidebar:
            with st.spinner("Scanning Results..."):
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                res = requests.get("https://api.theracingapi.com/v1/results", auth=auth)
                results_data = res.json().get('results', [])
                
                winners = [str(runner.get('horse')).upper().strip() 
                           for race in results_data 
                           for runner in race.get('runners', []) 
                           if str(runner.get('position')) == "1"]
                
                def process_row(row):
                    if row['Result'] == "Pending":
                        h_name = str(row['Horse']).upper().strip()
                        if h_name in winners:
                            row['Result'] = "Winner"
                            row['P/L'] = float(row['Odds']) - 1
                        elif len(winners) > 0:
                            row['Result'] = "Loser"
                            row['P/L'] = -1.0
                    return row

                updated_ledger = ledger.apply(process_row, axis=1)
                if conn:
                    conn.update(spreadsheet=GSHEET_URL, data=updated_ledger)
                    st.sidebar.success("Sheet Updated!")

# --- 3. SCORING & ODDS LOGIC ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and sp_val not in ['-', '', 'N/A']:
        try: return float(sp_val)
        except: pass
    
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list) and len(odds_list):
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
            if win_pc > 25: s += 20
            elif win_pc > 15: s += 10
        except: pass
    rtf = str(h.get('trainer_rtf', '0')).replace('%','')
    try:
        if float(rtf) > 50: s += 5
    except: pass
    return s

# --- 4. MAIN ANALYSIS ---
if st.button('🚀 Run Analysis'):
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
    data = r.json()
    races = data.get('racecards', [])
    
    if not races:
        r = requests.get("https://api.theracingapi.com/v1/results", auth=auth)
        races = r.json().get('results', [])

    if races:
        all_value_horses = []
        for race in races:
            for r in race.get('runners', []):
                odds = get_best_odds(r)
                score = get_score(r)
                # USE THE SLIDER VALUE HERE
                if score >= min_score and odds >= 5.0:
                    all_value_horses.append({
                        "Date": datetime.now().strftime("%Y-%m-%d"),
                        "Horse": r.get('horse'),
                        "Course": race.get('course'),
                        "Odds": odds,
                        "Score": score,
                        "Result": "Pending",
                        "P/L": 0.0
                    })

        if all_value_horses:
            st.subheader(f"🌟 Value Bets (Score {min_score}+)")
            top_3 = sorted(all_value_horses, key=lambda x: x['Score'], reverse=True)[:3]
            cols = st.columns(3)
            for i, h in enumerate(top_3):
                with cols[i]:
                    st.metric(label=f"{h['Horse']}", value=f"{int(h['Odds']-1)}/1", delta=f"Score: {h['Score']}")
            
            if st.button("📤 Log Today's Value Bets"):
                if conn:
                    existing = load_ledger()
                    new_bets = pd.DataFrame(all_value_horses)
                    filtered = new_bets[~new_bets['Horse'].isin(existing['Horse'])]
                    if not filtered.empty:
                        conn.update(spreadsheet=GSHEET_URL, data=pd.concat([existing, filtered], ignore_index=True))
                        st.success("Logged!")
    else:
        st.warning("No racing data found.")
