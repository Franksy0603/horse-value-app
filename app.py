import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. INITIAL SETTINGS ---
st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Automated Ledger")

API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 2. GOOGLE SHEETS CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except Exception as e:
    st.sidebar.error(f"Connection Error: {e}")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            return conn.read(spreadsheet=GSHEET_URL, ttl=0)
        except:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "P/L"])

# --- 3. THE FIX: LIVE RECONCILIATION ---
def reconcile_results():
    df = load_ledger()
    if df.empty:
        st.sidebar.warning("Ledger is empty.")
        return

    # Check for Pending bets
    pending_mask = df['Result'].str.strip().str.title() == 'Pending'
    if not pending_mask.any():
        st.sidebar.info("No 'Pending' bets to settle.")
        return

    st.sidebar.info("🔄 Fetching Live Results...")
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    
    # WE USE /live TO AVOID THE 422 ERROR
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
    
    if r.status_code == 200:
        results_data = r.json().get('results', [])
        winners_list = []
        for race in results_data:
            c_name = str(race.get('course', '')).upper().strip()
            for runner in race.get('runners', []):
                if str(runner.get('position')) == '1':
                    h_name = str(runner.get('horse', '')).upper().strip()
                    winners_list.append(f"{c_name}|{h_name}")
        
        match_count = 0
        today = datetime.now().date()
        
        for index, row in df.iterrows():
            if str(row['Result']).strip().title() == 'Pending':
                lookup = f"{str(row['Course']).upper().strip()}|{str(row['Horse']).upper().strip()}"
                
                if lookup in winners_list:
                    df.at[index, 'Result'] = 'Winner'
                    df.at[index, 'P/L'] = float(row['Odds']) - 1
                    match_count += 1
                else:
                    # Mark as Loser only if the race was on a previous day
                    try:
                        race_date = datetime.strptime(str(row['Date']), "%Y-%m-%d").date()
                        if race_date < today:
                            df.at[index, 'Result'] = 'Loser'
                            df.at[index, 'P/L'] = -1.0
                            match_count += 1
                    except: continue

        if match_count > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.sidebar.success(f"✅ Settled {match_count} bets!")
            st.rerun()
        else:
            st.sidebar.warning("No new results found in the live feed.")
    else:
        st.sidebar.error(f"API Error: {r.status_code}")

# --- 4. DASHBOARD & UI ---
st.sidebar.header("📊 Performance")
stake_val = st.sidebar.number_input("Stake (£)", min_value=1, value=10)

df_stats = load_ledger()
if not df_stats.empty:
    df_stats['P/L'] = pd.to_numeric(df_stats['P/L'], errors='coerce').fillna(0)
    profit = (df_stats['P/L'] * stake_val).sum()
    st.sidebar.metric("Total Profit", f"£{profit:,.2f}")
    if st.sidebar.button("🔄 Reconcile Results"):
        reconcile_results()

# --- 5. RACECARD ANALYSIS ---
if st.button('🚀 Run Analysis'):
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
    if r.status_code == 200:
        st.session_state.all_races = r.json().get('racecards', [])
        st.success("Analysis Complete!")

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"{race.get('off_time')} - {race.get('course')}"):
            st.write(f"Runners: {len(race.get('runners', []))}")
