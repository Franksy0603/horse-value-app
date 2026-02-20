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
st.title("🏇 Value Finder Pro: Google Sheets Ledger")

# Establish Google Sheets Connection
conn = st.connection("gsheets", type=GSheetsConnection)

# --- 2. SIDEBAR PERFORMANCE TRACKER ---
st.sidebar.header("📊 Performance Ledger")

def load_ledger():
    try:
        # ttl=0 ensures we always get the freshest data from the sheet
        return conn.read(spreadsheet=GSHEET_URL, ttl=0)
    except Exception as e:
        # Fallback if sheet is empty or inaccessible
        return pd.DataFrame(columns=["Date", "Horse", "Course", "Odds", "Score", "Result", "P/L"])

if st.sidebar.button("🔄 Reconcile Results"):
    ledger = load_ledger()
    if not ledger.empty and "Pending" in ledger['Result'].values:
        with st.sidebar:
            with st.spinner("Scanning Results API..."):
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                # Check results endpoint
                res = requests.get("https://api.theracingapi.com/v1/results", auth=auth)
                results_data = res.json().get('results', [])
                
                # Build a simple list of today's winners
                winners = []
                for race in results_data:
                    for runner in race.get('runners', []):
                        if str(runner.get('position')) == "1":
                            winners.append(str(runner.get('horse')).upper().strip())
                
                def process_row(row):
                    if row['Result'] == "Pending":
                        h_name = str(row['Horse']).upper().strip()
                        if h_name in winners:
                            row['Result'] = "Winner"
                            row['P/L'] = float(row['Odds']) - 1
                        elif len(winners) > 0: # Only mark loss if API actually returned results
                            row['Result'] = "Loser"
                            row['P/L'] = -1.0
                    return row

                updated_ledger = ledger.apply(process_row, axis=1)
                conn.update(spreadsheet=GSHEET_URL, data=updated_ledger)
                st.sidebar.success("Sheet Updated Successfully!")
    else:
        st.sidebar.info("No 'Pending' bets to reconcile.")

if st.sidebar.button("📈 Show Lifetime Stats"):
    ledger = load_ledger()
    if not ledger.empty:
        # Convert P/L to numeric to handle any empty strings/errors
        pl_values = pd.to_numeric(ledger['P/L'], errors='coerce').fillna(0)
        total_pl = pl_values.sum()
        st.sidebar.metric("Total Profit/Loss", f"{total_pl:.2f} pts", delta=f"{total_pl:.2f}")
        st.sidebar.dataframe(ledger.tail(10), hide_index=True)

# --- 3. SCORING & ODDS LOGIC ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and sp_val not in ['-', '', 'N/A']:
        try: return float(sp_val)
        except: pass
    
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list) and len(odds_list) > 0:
        prices = []
        for entry in odds_list:
            d_val = entry.get('decimal')
            if d_val and d_val not in ['-', 'SP', '', 'None']:
                try: prices.append(float(d_val))
                except: continue
        if prices: return max(prices)
    return 0.0

def get_score(h):
    s = 0
    form = str(h.get('form', ''))
    if form and form.endswith('1'): s += 15
    
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            t_win = float(t_stats.get('percent', 0))
            if t_win > 25: s += 20
            elif t_win > 15: s += 10
        except: pass
    
    rtf = str(h.get('trainer_rtf', '0')).replace('%','')
    try:
        if float(rtf) > 50: s += 5
    except: pass
    return s

# --- 4. MAIN ANALYSIS ---
if st.button('🚀 Run Analysis'):
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    # Try Racecards (Future)
    r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
    data = r.json()
    races = data.get('racecards', [])
    
    # Fallback to Results (Past/Live)
    if not races:
        r = requests.get("https://api.theracingapi.com/v1/results", auth=auth)
        races = r.json().get('results', [])

    if races:
        all_value_horses = []
        for race in races:
            for r in race.get('runners', []):
                odds = get_best_odds(r)
                score = get_score(r)
                # Value = Score 20+ and Odds 4/1 ($5.0) +
                if score >= 20 and odds >= 5.0:
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
            st.subheader("🌟 Top 3 Daily Value Bets")
            top_3 = sorted(all_value_horses, key=lambda x: x['Score'], reverse=True)[:3]
            cols = st.columns(3)
            for i, h in enumerate(top_3):
                with cols[i]:
                    st.metric(label=f"{h['Horse']}", value=f"{int(h['Odds']-1)}/1", delta=f"Score: {h['Score']}")
            
            if st.button("📤 Log Today's Value Bets to Google Sheets"):
                existing = load_ledger()
                new_bets = pd.DataFrame(all_value_horses)
                # Avoid duplicates: only add horses not already in the sheet
                filtered_new = new_bets[~new_bets['Horse'].isin(existing['Horse'])]
                
                if not filtered_new.empty:
                    updated_df = pd.concat([existing, filtered_new], ignore_index=True)
                    conn.update(spreadsheet=GSHEET_URL, data=updated_df)
                    st.success(f"Logged {len(filtered_new)} new horses to the Cloud!")
                else:
                    st.info("Today's horses are already logged.")

        # Meeting Breakdown
        for race in races:
            course_name = race.get('course', 'Unknown')
            time = race.get('off_time', race.get('off', '00:00'))
            with st.expander(f"🕒 {time} - {course_name}"):
                runners = race.get('runners', [])
                table_data = []
                for runner in runners:
                    s = get_score(runner)
                    o = get_best_odds(runner)
                    table_data.append({
                        "Horse": runner.get('horse'),
                        "Score": s,
                        "Odds": f"{int(o-1)}/1" if o > 1 else "SP",
                        "Value": "💎 YES" if (s >= 20 and o >= 5.0) else ""
                    })
                st.table(pd.DataFrame(table_data))
    else:
        st.warning("No racing data found. Check your API credentials or try again later.")
