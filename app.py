import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & SECRETS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Automated Ledger")

if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 2. SECURE CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Secure API Linked")
except Exception as e:
    st.sidebar.error(f"❌ Connection Error: {str(e)}")
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

# --- 3. HELPER: ULTIMATE CLEANER ---
def clean_name(name):
    if not name or pd.isna(name): return ""
    text = str(name).upper()
    text = re.sub(r'\(.*?\)', '', text) # Remove (GB), (AUS), etc.
    text = re.sub(r'[^A-Z0-9\s]', '', text) # Remove punctuation
    return " ".join(text.split()).strip()

# --- 4. DATA PROCESSING ENGINE ---
def process_data_and_update(file_data):
    all_positions = {} 
    results_list = file_data.get('results', [])
    
    for race in results_list:
        course_name = clean_name(race.get('course', '')) 
        for runner in race.get('runners', []):
            horse_name = clean_name(runner.get('horse', ''))
            pos_val = runner.get('position')
            if pos_val is not None:
                all_positions[f"{course_name}|{horse_name}"] = str(pos_val)

    df = load_ledger()
    if 'Pos' not in df.columns: df['Pos'] = "-"
    
    match_count = 0
    for index, row in df.iterrows():
        # FUZZY STATUS CHECK: Catches "Pending", "pending", "Pending "
        current_status = str(row.get('Result', '')).strip().upper()
        
        if current_status == "PENDING":
            c_name = clean_name(row.get('Course', ''))
            h_name = clean_name(row.get('Horse', ''))
            lookup_key = f"{c_name}|{h_name}"
            
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
        st.sidebar.success(f"✅ Updated {match_count} results!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found. Ensure the horse name in your sheet matches the JSON horse name.")

# --- 5. PERFORMANCE DASHBOARD (RESTORED) ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        # Calculate Stats
        df['P/L_Num'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake_Num'] = pd.to_numeric(df.get('Stake', s_val), errors='coerce').fillna(s_val)
        
        total_profit_cash = (df['P/L_Num'] * df['Stake_Num']).sum()
        total_invested = df['Stake_Num'].sum()
        roi = (total_profit_cash / total_invested * 100) if total_invested > 0 else 0
        
        # Display Metrics
        color = "green" if total_profit_cash >= 0 else "red"
        st.sidebar.markdown(f"### Profit: :{color}[£{total_profit_cash:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested:,.0f}")
        c2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        # Sync Buttons
        if st.sidebar.button("🔄 Auto Reconcile (Live API)"):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
            if r.status_code == 200: process_data_and_update(r.json())
            else: st.sidebar.error(f"API Error {r.status_code}")

        uploaded_file = st.sidebar.file_uploader("📂 Manual JSON Update", type=["json"])
        if uploaded_file and st.sidebar.button("🚀 Sync from File"):
            process_data_and_update(json.load(uploaded_file))
    else:
        st.sidebar.info("Ledger is empty.")

display_sidebar_stats(stake_input)

# --- 6. ANALYSIS & LOGGING ---
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
    with st.spinner("Analyzing cards..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for r_data in race.get('runners', []):
                    odds, score = get_best_odds(r_data), get_score(r_data)
                    if score >= min_score and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'), "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')), "Odds": odds,
                            "Score": score, "Stake": stake_input, 
                            "Result": "Pending", "Pos": "-", "P/L": 0.0
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 GOLD VALUE BETS")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            st.markdown(f'<div style="background-color:#FFD700; padding:20px; border-radius:10px; border:2px solid #DAA520; text-align:center; color:#000;"><h2>{h["Horse"]}</h2><p><b>{h["Time"]} - {h["Course"]}</b></p><hr><b>Score: {h["Score"]}</b><br>Odds: {int(h["Odds"]-1)}/1</div>', unsafe_allow_html=True)
    
    if st.button("📤 LOG SELECTIONS TO GOOGLE SHEETS"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        today_str = datetime.now().strftime("%Y-%m-%d")
        filtered = new_df[~new_df['Horse'].isin(ledger[ledger['Date'] == today_str]['Horse'])]
        if not filtered.empty:
            conn.update(spreadsheet=GSHEET_URL, data=pd.concat([ledger, filtered], ignore_index=True))
            st.balloons()
            st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
            st.table(pd.DataFrame([{"Horse": r.get('horse'), "Score": get_score(r), "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP", "Value": "💎 YES" if (get_score(r) >= min_score and get_best_odds(r) >= 5.0) else ""} for r in race.get('runners', [])]))
