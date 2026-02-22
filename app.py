import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Automated Ledger")

if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 2. CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except Exception as e:
    st.sidebar.error("❌ Connection Error")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L"])

# --- 3. THE "CLEANER" (Fixes the naming mismatch) ---
def clean_name(name):
    if not name or pd.isna(name): return ""
    text = str(name).upper()
    text = re.sub(r'\(.*?\)', '', text) # Strips (GB), (AW), (IRE)
    text = re.sub(r'[^A-Z0-9\s]', '', text) # Strips apostrophes/dots
    return " ".join(text.split()).strip()

# --- 4. DATA SYNC ENGINE (Matches your specific JSON) ---
def process_data_and_update(file_data):
    all_positions = {} 
    # Use the 'results' key from your specific JSON file
    results_list = file_data.get('results', [])
    
    for race in results_list:
        course_json = clean_name(race.get('course', ''))
        for runner in race.get('runners', []):
            horse_json = clean_name(runner.get('horse', ''))
            pos_val = runner.get('position')
            if pos_val:
                all_positions[f"{course_json}|{horse_json}"] = str(pos_val)

    df = load_ledger()
    if 'Pos' not in df.columns: df['Pos'] = "-"
    
    match_count = 0
    for index, row in df.iterrows():
        # Check for 'Pending' regardless of case/spaces
        if str(row.get('Result', '')).strip().upper() == "PENDING":
            c_sheet = clean_name(row.get('Course', ''))
            h_sheet = clean_name(row.get('Horse', ''))
            lookup_key = f"{c_sheet}|{h_sheet}"
            
            if lookup_key in all_positions:
                actual_pos = all_positions[lookup_key]
                df.at[index, 'Pos'] = actual_pos
                
                if actual_pos == '1':
                    df.at[index, 'Result'] = 'Winner'
                    odds = pd.to_numeric(row['Odds'], errors='coerce') or 1.0
                    df.at[index, 'P/L'] = odds - 1
                else:
                    df.at[index, 'Result'] = 'Loser'
                    df.at[index, 'P/L'] = -1.0
                match_count += 1
    
    if match_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Synced {match_count} Bets!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found. Check that the Horse names in your sheet match the JSON.")

# --- 5. RESTORED PERFORMANCE DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_stats(s_val):
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        # Robust Math conversion
        df['PL_VAL'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['STK_VAL'] = pd.to_numeric(df.get('Stake', s_val), errors='coerce').fillna(s_val)
        
        cash_profit = (df['PL_VAL'] * df['STK_VAL']).sum()
        total_spent = df['STK_VAL'].sum()
        roi = (cash_profit / total_spent * 100) if total_spent > 0 else 0
        
        color = "green" if cash_profit >= 0 else "red"
        st.sidebar.markdown(f"### Total Profit: :{color}[£{cash_profit:,.2f}]")
        
        col1, col2 = st.sidebar.columns(2)
        col1.metric("Invested", f"£{total_spent:,.0f}")
        col2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        if st.sidebar.button("🔄 Auto Reconcile (Live)"):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
            if r.status_code == 200: process_data_and_update(r.json())
            else: st.sidebar.error("API Locked")

        uploaded = st.sidebar.file_uploader("📂 Manual JSON Update", type=["json"])
        if uploaded and st.sidebar.button("🚀 Sync from File"):
            process_data_and_update(json.load(uploaded))
    else:
        st.sidebar.info("Ledger is empty.")

display_stats(stake_input)

# --- 6. ANALYSIS LOGIC (Card fetching) ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and str(sp_val).replace('.','',1).isdigit(): return float(sp_val)
    prices = [float(e.get('decimal')) for e in runner.get('odds', []) if str(e.get('decimal', '')).replace('.','',1).isdigit()]
    return max(prices) if prices else 0.0

def get_score(h):
    s = 0
    if str(h.get('form', '')).endswith('1'): s += 15
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            win_pc = float(t_stats.get('percent', 0))
            if win_pc > 20: s += 15
            elif win_pc > 10: s += 5
        except: pass
    return s

st.sidebar.markdown("---")
min_score = st.sidebar.slider("Min Value Score", 0, 50, 20, 5)

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing..."):
        auth = HTTPBasicAuth(API_USER, API_PASS)
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for r_data in race.get('runners', []):
                    o, s = get_best_odds(r_data), get_score(r_data)
                    if s >= min_score and o >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'), "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')), "Odds": o,
                            "Score": s, "Stake": stake_input, 
                            "Result": "Pending", "Pos": "-", "P/L": 0.0
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 GOLD VALUE BETS")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            st.markdown(f'<div style="background-color:#FFD700; padding:20px; border-radius:10px; border:2px solid #DAA520; text-align:center; color:#000;"><h2>{h["Horse"]}</h2><b>Score: {h["Score"]}</b></div>', unsafe_allow_html=True)
    
    if st.button("📤 LOG TO GOOGLE SHEETS"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        today = datetime.now().strftime("%Y-%m-%d")
        filtered = new_df[~new_df['Horse'].isin(ledger[ledger['Date'] == today]['Horse'])]
        if not filtered.empty:
            conn.update(spreadsheet=GSHEET_URL, data=pd.concat([ledger, filtered], ignore_index=True))
            st.balloons()
            st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('course')}"):
            st.table(pd.DataFrame([{"Horse": r.get('horse'), "Score": get_score(r)} for r in race.get('runners', [])]))
