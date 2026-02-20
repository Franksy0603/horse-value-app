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
st.title("🏇 Value Finder Pro: Ledger Edition")

# Initialize Session State so results don't disappear
if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 2. SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Controls")
min_score = st.sidebar.slider("Minimum Value Score", 0, 50, 20, 5)

st.sidebar.markdown("---")
st.sidebar.header("📊 Performance Ledger")

conn = None
if HAS_GSHEETS and GSHEET_URL:
    try:
        conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
        st.sidebar.success("✅ Sheets API Linked")
    except Exception as e:
        st.sidebar.error(f"❌ Connection Error: {str(e)}")

def load_ledger():
    if conn and GSHEET_URL:
        try:
            return conn.read(spreadsheet=GSHEET_URL, ttl=0)
        except Exception:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Odds", "Score", "Result", "P/L"])

if st.sidebar.button("🔄 Reconcile Results"):
    ledger = load_ledger()
    if not ledger.empty and "Pending" in ledger['Result'].values:
        with st.sidebar:
            status = st.empty()
            status.info("Checking API...")
            try:
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                res = requests.get("https://api.theracingapi.com/v1/results", auth=auth, timeout=15)
                winners = [str(r.get('horse')).upper().strip() 
                           for race in res.json().get('results', []) 
                           for r in race.get('runners', []) if str(r.get('position')) == "1"]
                
                if winners:
                    def process_row(row):
                        if row['Result'] == "Pending":
                            h_name = str(row['Horse']).upper().strip()
                            if h_name in winners:
                                row['Result'] = "Winner"
                                row['P/L'] = float(row['Odds']) - 1
                            else:
                                row['Result'] = "Loser"
                                row['P/L'] = -1.0
                        return row
                    updated_ledger = ledger.apply(process_row, axis=1)
                    conn.update(spreadsheet=GSHEET_URL, data=updated_ledger)
                    status.success("✅ Ledger Updated!")
                else:
                    status.warning("No new winners found.")
            except Exception as e:
                status.error(f"Error: {str(e)}")

# --- 3. ODDS & SCORING ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and sp_val not in ['-', '', 'N/A', 'None']:
        try: return float(sp_val)
        except: pass
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list) and len(odds_list) > 0:
        prices = []
        for e in odds_list:
            d_val = e.get('decimal')
            if d_val is not None and d_val not in ['-', 'SP', 'None', '']:
                try: prices.append(float(d_val))
                except: continue
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
    with st.spinner("Fetching Racecards..."):
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

# DISPLAY RESULTS IF THEY EXIST
if st.session_state.value_horses:
    st.markdown("### 🏆 Top Value Bets")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            # This 'st.success' creates the green/gold highlighted block
            st.success(f"### {h['Horse']}")
            st.write(f"**Score:** {h['Score']} | **Odds:** {int(h['Odds']-1)}/1")

    st.markdown("---")
    if st.button("📤 LOG SELECTIONS TO GOOGLE SHEETS"):
        if conn:
            try:
                existing = load_ledger()
                new_data = pd.DataFrame(st.session_state.value_horses)
                # Avoid duplicates
                filtered = new_data[~new_data['Horse'].isin(existing['Horse'])]
                
                if not filtered.empty:
                    updated_df = pd.concat([existing, filtered], ignore_index=True)
                    conn.update(spreadsheet=GSHEET_URL, data=updated_df)
                    st.balloons()
                    st.success(f"Logged {len(filtered)} horses!")
                else:
                    st.info("Horses already in ledger.")
            except Exception as e:
                st.error(f"Logging Failed: {e}")

# Breakdown Tables
if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
            runners = race.get('runners', [])
            table_data = []
            for runner in runners:
                s = get_score(runner)
                o = get_best_odds(runner)
                table_data.append({
                    "Horse": runner.get('horse'),
                    "Score": s,
                    "Odds": f"{int(o-1)}/1" if o > 1 else "SP",
                    "Value": "💎 VALUE" if (s >= min_score and o >= 5.0) else ""
                })
            st.table(pd.DataFrame(table_data))
