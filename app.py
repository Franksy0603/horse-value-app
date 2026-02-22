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

# Initialize session state
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
            # Ensure headers are strings and trimmed
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L"])

# --- 3. HELPER: THE ULTIMATE CLEANER ---
def clean_name(name):
    """Removes (GB), (AUS), (AW), and all non-alphanumeric junk."""
    if not name or pd.isna(name): return ""
    text = str(name).upper()
    # Remove anything in brackets/parentheses
    text = re.sub(r'\(.*?\)', '', text)
    # Remove non-alphanumeric characters
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    return " ".join(text.split()).strip()

# --- 4. DATA PROCESSING ENGINE ---
def process_data_and_update(file_data):
    all_positions = {} 
    results_list = file_data.get('results', [])
    
    # 1. Map normalized names to positions from API/JSON data
    for race in results_list:
        course_name = clean_name(race.get('course', '')) 
        for runner in race.get('runners', []):
            horse_name = clean_name(runner.get('horse', ''))
            pos_val = runner.get('position')
            if pos_val is not None:
                all_positions[f"{course_name}|{horse_name}"] = str(pos_val)

    df = load_ledger()
    
    # Critical Check: Ensure required columns exist
    required = ["Course", "Horse", "Result", "Odds", "P/L"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.sidebar.error(f"Missing columns in Sheet: {missing}")
        return

    if 'Pos' not in df.columns: df['Pos'] = "-"
    
    match_count = 0
    for index, row in df.iterrows():
        # Only process 'Pending' rows
        res_val = str(row['Result']).strip().title()
        if res_val == 'Pending':
            c_name = clean_name(row['Course'])
            h_name = clean_name(row['Horse'])
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
        st.sidebar.success(f"✅ Successfully updated {match_count} bets!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found. Check Horse/Course names.")

# --- 5. PERFORMANCE DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        total_pl = (df['P/L'] * s_val).sum()
        st.sidebar.metric("Total Profit", f"£{total_pl:,.2f}")
        
        st.sidebar.markdown("---")
        if st.sidebar.button("🔄 Auto Reconcile (Live)"):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            try:
                r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
                if r.status_code == 200: process_data_and_update(r.json())
                else: st.sidebar.error(f"API Error {r.status_code}")
            except Exception as e: st.sidebar.error(f"Sync failed: {e}")

        uploaded_file = st.sidebar.file_uploader("Upload Results JSON", type=["json"])
        if uploaded_file and st.sidebar.button("🚀 Sync from File"):
            process_data_and_update(json.load(uploaded_file))
    else:
        st.sidebar.info("Ledger is empty or columns are misaligned.")

display_sidebar_stats(stake_input)

# --- 6. DATA PROCESSING ---
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

# --- 7. MAIN INTERFACE ---
st.sidebar.markdown("---")
min_score = st.sidebar.slider("Min Value Score", 0, 50, 20, 5)

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing today's value..."):
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
