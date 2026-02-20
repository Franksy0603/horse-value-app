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
min_score = st.sidebar.slider("Minimum Value Score", 0, 50, 20, 5)

st.sidebar.markdown("---")
st.sidebar.header("📊 Performance Ledger")

conn = None
if HAS_GSHEETS and GSHEET_URL:
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
    except Exception:
        st.sidebar.warning("⚠️ Sheet Connection Failed")

def load_ledger():
    if conn and GSHEET_URL:
        try:
            # We fetch the sheet with ttl=0 to ensure we see the 'Pending' status immediately
            return conn.read(spreadsheet=GSHEET_URL, ttl=0)
        except Exception:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Odds", "Score", "Result", "P/L"])

if st.sidebar.button("🔄 Reconcile Results"):
    ledger = load_ledger()
    # Debug info to help you see why it might be failing
    if ledger.empty:
        st.sidebar.error("Sheet is empty. Log some bets first!")
    elif "Pending" not in ledger['Result'].values:
        st.sidebar.warning(f"Found {len(ledger)} rows, but none are marked as 'Pending'.")
    else:
        with st.sidebar:
            status = st.empty()
            status.info("Checking API for winners...")
            try:
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                res = requests.get("https://api.theracingapi.com/v1/results", auth=auth, timeout=15)
                results_data = res.json().get('results', [])
                
                # Create list of winning horses
                winners = [str(runner.get('horse')).upper().strip() 
                           for race in results_data 
                           for runner in race.get('runners', []) 
                           if str(runner.get('position')) == "1"]
                
                if winners:
                    def process_row(row):
                        if row['Result'] == "Pending":
                            h_name = str(row['Horse']).upper().strip()
                            if h_name in winners:
                                row['Result'] = "Winner"
                                row['P/L'] = float(row['Odds']) - 1
                            else:
                                # We only mark as Loser if the race is actually finished (found in results)
                                row['Result'] = "Loser"
                                row['P/L'] = -1.0
                        return row

                    updated_ledger = ledger.apply(process_row, axis=1)
                    conn.update(spreadsheet=GSHEET_URL, data=updated_ledger)
                    status.success("✅ Ledger Updated!")
                else:
                    status.warning("API results are in, but no winners matched your bets yet.")
            except Exception as e:
                status.error(f"Error: {str(e)}")

# --- 3. SCORING & ODDS LOGIC ---
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
            for r_data in race.get('runners', []):
                odds = get_best_odds(r_data)
                score = get_score(r_data)
                if score >= min_score and odds >= 5.0:
                    all_value_horses.append({
                        "Date": datetime.now().strftime("%Y-%m-%d"),
                        "Horse": r_data.get('horse'),
                        "Course": race.get('course'),
                        "Odds": odds,
                        "Score": score,
                        "Result": "Pending",
                        "P/L": 0.0
                    })

        if all_value_horses:
            st.markdown("### 🏆 Top Daily Value Bets")
            top_3 = sorted(all_value_horses, key=lambda x: x['Score'], reverse=True)[:3]
            cols = st.columns(3)
            for i, h in enumerate(top_3):
                with cols[i]:
                    # Using a colored info box to simulate the 'Gold' look
                    st.info(f"### {h['Horse']}")
                    st.write(f"**Score:** {h['Score']} | **Odds:** {int(h['Odds']-1)}/1")
            
            if st.button("📤 Log Today's Value Bets to Google Sheets"):
                if conn:
                    existing = load_ledger()
                    new_bets = pd.DataFrame(all_value_horses)
                    filtered = new_bets[~new_bets['Horse'].isin(existing['Horse'])]
                    if not filtered.empty:
                        updated_df = pd.concat([existing, filtered], ignore_index=True)
                        conn.update(spreadsheet=GSHEET_URL, data=updated_df)
                        st.balloons()
                        st.success("Successfully Logged!")
        
        # Breakdown Tables
        for race in races:
            with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
                runners = race.get('runners', [])
                table_data = []
                for runner in runners:
                    s = get_score(runner)
                    o = get_best_odds(runner)
                    is_value = (s >= min_score and o >= 5.0)
                    table_data.append({
                        "Horse": runner.get('horse'),
                        "Score": s,
                        "Odds": f"{int(o-1)}/1" if o > 1 else "SP",
                        "Value": "💎 VALUE" if is_value else ""
                    })
                st.table(pd.DataFrame(table_data))
    else:
        st.warning("No data found. Check your API credentials.")
