import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & SECRETS ---
st.set_page_config(page_title="Value Finder Pro", layout="wide")
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

# --- 2. INITIALIZE SESSION STATE ---
if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 3. SECURE CONNECTION ---
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
            if df is not None:
                df.columns = [str(c).strip() for c in df.columns]
                for col in ["P/L", "Stake", "Odds"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                return df
        except Exception as e:
            st.error(f"⚠️ Sheet Load Error: {e}")
    return pd.DataFrame()

# --- 4. RECONCILE LOGIC ---
def clean_txt(text):
    if not text: return ""
    text = str(text).upper()
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text.strip()

def process_reconciliation(data):
    try:
        results_map = {}
        for race in data.get('results', []):
            c_key = clean_txt(race.get('course', ''))
            for runner in race.get('runners', []):
                h_key = clean_txt(runner.get('horse', ''))
                results_map[f"{c_key}|{h_key}"] = str(runner.get('position', ''))

        df = load_ledger()
        if df.empty: return

        settled = 0
        for i, row in df.iterrows():
            if str(row.get('Result', '')).strip().upper() in ['PENDING', '-', '']:
                l_key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
                if l_key in results_map:
                    pos = results_map[l_key]
                    df.at[i, 'Pos'] = pos
                    stake = float(row.get('Stake', 10))
                    if pos == '1':
                        df.at[i, 'Result'] = 'Winner'
                        df.at[i, 'P/L'] = (float(row.get('Odds', 1)) - 1) * stake
                    else:
                        df.at[i, 'Result'] = 'Loser'
                        df.at[i, 'P/L'] = -stake
                    settled += 1

        if settled > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.success(f"Settled {settled} bets!")
            st.rerun()
    except Exception as e:
        st.error(f"Update Error: {e}")

# --- 5. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
ledger = load_ledger()
if not ledger.empty:
    profit = (ledger['P/L']).sum()
    st.sidebar.markdown(f"### Profit: :{'green' if profit >= 0 else 'red'}[£{profit:,.2f}]")
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🔄 Reconcile Results")
    uploaded_file = st.sidebar.file_uploader("Upload JSON File", type=["json"])
    if uploaded_file and st.sidebar.button("🚀 Process Manual Upload"):
        process_reconciliation(json.load(uploaded_file))

    if st.sidebar.button("🔄 Auto-Sync"):
        auth = HTTPBasicAuth(API_USER, API_PASS)
        d_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={d_str}", auth=auth)
        if r.status_code == 200: process_reconciliation(r.json())

# --- 6. MAIN INTERFACE ---
st.title("🏇 Value Finder Pro: Automated Ledger")

if st.button('🚀 Run Analysis'):
    with st.spinner("Finding value..."):
        auth = HTTPBasicAuth(API_USER, API_PASS)
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for runner in race.get('runners', []):
                    # Trainer check with error safety
                    raw_pc = runner.get('trainer_14_days', {}).get('percent', 0)
                    t_pc = pd.to_numeric(raw_pc, errors='coerce') or 0
                    
                    score = 0
                    if str(runner.get('form', '')).endswith('1'): score += 15
                    if t_pc > 15: score += 15
                    
                    if score >= 15:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": runner.get('horse'),
                            "Course": race.get('course'),
                            "Odds": float(runner.get('sp_dec', 1)),
                            "Score": score,
                            "Stake": 10.0,
                            "Result": "Pending",
                            "Pos": "-",
                            "P/L": 0.0,
                            "Time": race.get('off_time', '')
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 Gold Bets")
    cols = st.columns(min(3, len(st.session_state.value_horses)))
    for i, h in enumerate(st.session_state.value_horses[:3]):
        with cols[i]:
            st.markdown(f"""
            <div style="background-color:#FFD700; padding:20px; border-radius:10px; border:2px solid #DAA520; text-align:center; color:#000;">
                <h2 style="margin:0; color:#000;">{h['Horse']}</h2>
                <p style="margin:5px 0; font-size:16px;"><b>{h['Time']} - {h['Course']}</b></p>
                <hr style="border-top: 1px solid #DAA520;">
                <p style="font-size:20px; margin:5px;"><b>Score: {h['Score']}</b></p>
            </div>
            """, unsafe_allow_html=True)

    if st.button("📤 Log All Selections"):
        df_new = pd.DataFrame(st.session_state.value_horses)
        cols_order = ["Date", "Horse", "Course", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Time"]
        df_new = df_new[cols_order]
        updated = pd.concat([load_ledger(), df_new], ignore_index=True)
        conn.update(spreadsheet=GSHEET_URL, data=updated)
        st.success("Logged!")

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('course')} - {race.get('off_time')}"):
            st.table(pd.DataFrame([{"Horse": r.get('horse'), "SP": r.get('sp_dec')} for r in race.get('runners', [])]))
