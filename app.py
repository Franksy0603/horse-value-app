import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & PAGE CONFIG ---
st.set_page_config(page_title="Value Finder Pro", layout="wide")

# --- 2. INITIALIZE SESSION STATE ---
if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 3. SECURE CONNECTION ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except Exception as e:
    st.sidebar.error("❌ Sheet Connection Failed")
    conn = None

# --- 4. DATA CLEANING & RECONCILE ENGINE ---
def clean_txt(text):
    if not text or pd.isna(text): return ""
    text = str(text).upper()
    text = re.sub(r'\(.*?\)', '', text)  
    text = re.sub(r'[^A-Z0-9]', '', text) 
    return text.strip()

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            if df is not None:
                df.columns = [str(c).strip() for c in df.columns]
                for col in ["P/L", "Stake", "Odds", "Score"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                return df
        except Exception as e:
            st.error(f"⚠️ Error loading ledger: {e}")
    return pd.DataFrame()

def run_reconciliation(data):
    results_map = {}
    for race in data.get('results', []):
        c_clean = clean_txt(race.get('course', ''))
        for runner in race.get('runners', []):
            h_clean = clean_txt(runner.get('horse', ''))
            key = f"{c_clean}|{h_clean}"
            results_map[key] = {"pos": str(runner.get('position', '')), "sp": runner.get('sp_dec', 1.0)}

    df = load_ledger()
    if df.empty: return

    updated_count = 0
    for i, row in df.iterrows():
        res_val = str(row.get('Result', '')).strip().upper()
        if res_val in ['PENDING', '-', '', 'NAN']:
            lookup_key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
            
            if lookup_key in results_map:
                res = results_map[lookup_key]
                df.at[i, 'Pos'] = res['pos']
                stake = float(row.get('Stake', 10))
                
                if res['pos'] == '1':
                    df.at[i, 'Result'] = 'Winner'
                    odds = pd.to_numeric(row.get('Odds'), errors='coerce')
                    if pd.isna(odds) or odds <= 1: odds = float(res['sp'])
                    df.at[i, 'P/L'] = (odds - 1) * stake
                else:
                    df.at[i, 'Result'] = 'Loser'
                    df.at[i, 'P/L'] = -stake
                updated_count += 1

    if updated_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.success(f"✅ Updated {updated_count} results!")
        st.rerun()

# --- 5. SIDEBAR & STATS ---
st.sidebar.header("📊 Performance")
ledger_df = load_ledger()

if not ledger_df.empty and "P/L" in ledger_df.columns:
    total_pl = ledger_df["P/L"].sum()
    total_staked = ledger_df["Stake"].sum()
    roi = (total_pl / total_staked * 100) if total_staked > 0 else 0
    color = "green" if total_pl >= 0 else "red"
    st.sidebar.markdown(f"### Profit: :{color}[£{total_pl:,.2f}]")
    st.sidebar.metric("ROI %", f"{roi:.1f}%")

st.sidebar.markdown("---")
st.sidebar.subheader("🔄 Reconcile")
manual_json = st.sidebar.file_uploader("Upload Yesterday's JSON", type=["json"])
if manual_json and st.sidebar.button("🚀 Process Manual Upload"):
    run_reconciliation(json.load(manual_json))

if st.sidebar.button("🔄 Auto-Sync (Last 24h)"):
    auth = HTTPBasicAuth(API_USER, API_PASS)
    yest = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={yest}", auth=auth)
    if r.status_code == 200: run_reconciliation(r.json())

# --- 6. MAIN GUI ---
st.title("🏇 Value Finder Pro")

if st.button('🚀 Run Analysis for Today'):
    with st.spinner("Analyzing Racecards..."):
        auth = HTTPBasicAuth(API_USER, API_PASS)
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            
            for race in st.session_state.all_races:
                for runner in race.get('runners', []):
                    # SAFE NUMBER CONVERSION
                    raw_perc = runner.get('trainer_14_days', {}).get('percent', 0)
                    trainer_pc = pd.to_numeric(raw_perc, errors='coerce')
                    if pd.isna(trainer_pc): trainer_pc = 0
                    
                    sp_val = pd.to_numeric(runner.get('sp_dec'), errors='coerce')
                    if pd.isna(sp_val): sp_val = 1.0
                    
                    score = 0
                    if str(runner.get('form', '')).endswith('1'): score += 15
                    if trainer_pc > 15: score += 15
                    
                    if score >= 15 and sp_val >= 4.0:
                        # Matches your order: Date, Horse, Course, Odds, Score, Stake, Result, Pos, P/L, Time
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": runner.get('horse'),
                            "Course": race.get('course'),
                            "Odds": sp_val,
                            "Score": score,
                            "Stake": 10.0,
                            "Result": "Pending",
                            "Pos": "-",
                            "P/L": 0.0,
                            "Time": race.get('off_time', race.get('off'))
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 Gold Selections")
    cols = st.columns(min(3, len(st.session_state.value_horses)))
    for i, h in enumerate(st.session_state.value_horses[:3]):
        with cols[i]:
            st.success(f"**{h['Horse']}**\n\n{h['Time']} {h['Course']}\n\nScore: {h['Score']} | Odds: {h['Odds']}")
    
    if st.button("📤 Log Selections to Google Sheets"):
        current_sheet = load_ledger()
        new_bets = pd.DataFrame(st.session_state.value_horses)
        
        # Ensure correct column order for your sheet
        cols_order = ["Date", "Horse", "Course", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Time"]
        new_bets = new_bets[cols_order]
        
        updated_sheet = pd.concat([current_sheet, new_bets], ignore_index=True)
        conn.update(spreadsheet=GSHEET_URL, data=updated_sheet)
        st.balloons()
        st.rerun()

if st.session_state.all_races:
    st.markdown("---")
    for race in st.session_state.all_races:
        with st.expander(f"{race.get('off_time')} {race.get('course')}"):
            st.table(pd.DataFrame([{"Horse": r.get('horse'), "SP": r.get('sp_dec')} for r in race.get('runners', [])]))
