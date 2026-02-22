import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & SECRETS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Automated Ledger")

# --- 2. INITIALIZE SESSION STATE (FIXES THE ERROR) ---
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
    text = re.sub(r'\b(AW|PARK|CITY|JUNCTION|ESTUARY|REGIONAL|ALL WEATHER)\b', '', text)
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text.strip()

def process_reconciliation(data):
    try:
        results_map = {}
        api_sample = []
        for race in data.get('results', []):
            c_clean = clean_txt(race.get('course', ''))
            for runner in race.get('runners', []):
                h_clean = clean_txt(runner.get('horse', ''))
                key = f"{c_clean}|{h_clean}"
                results_map[key] = str(runner.get('position', ''))
                api_sample.append(key)

        df = load_ledger()
        if df.empty: return

        settled_count = 0
        missed_log = []

        for i, row in df.iterrows():
            res_val = str(row.get('Result', '')).strip().upper()
            if res_val in ['PENDING', '-', '']:
                lookup_key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
                
                if lookup_key in results_map:
                    pos = results_map[lookup_key]
                    df.at[i, 'Pos'] = pos
                    if pos == '1':
                        df.at[i, 'Result'] = 'Winner'
                        df.at[i, 'P/L'] = float(row.get('Odds', 1)) - 1.0
                    else:
                        df.at[i, 'Result'] = 'Loser'
                        df.at[i, 'P/L'] = -1.0
                    settled_count += 1
                else:
                    missed_log.append(lookup_key)

        if settled_count > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.success(f"✅ Settled {settled_count} bets!")
            st.rerun()
        else:
            st.warning("No matches found.")
            with st.expander("🔍 Diagnostic Report"):
                st.write("**Sheet Looking For:**", missed_log[:10])
                st.write("**File Contains:**", api_sample[:10])
    except Exception as e:
        st.error(f"Reconciliation Error: {e}")

# --- 5. SIDEBAR ---
st.sidebar.header("📊 Dashboard")
stake_val = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats():
    try:
        df = load_ledger()
        if not df.empty:
            profit = (df['P/L'] * df['Stake']).sum()
            invested = df['Stake'].sum()
            color = "green" if profit >= 0 else "red"
            st.sidebar.markdown(f"### Profit: :{color}[£{profit:,.2f}]")
            
            st.sidebar.markdown("---")
            st.sidebar.subheader("🔄 Reconcile")
            uploaded_file = st.sidebar.file_uploader("Upload Results JSON", type=["json"])
            if uploaded_file and st.sidebar.button("🚀 Process Upload"):
                process_reconciliation(json.load(uploaded_file))

            if st.sidebar.button("🔄 Auto-Sync (Today/Yesterday)"):
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                combined = {"results": []}
                for day in [0, 1]:
                    d_str = (datetime.now() - timedelta(days=day)).strftime("%Y-%m-%d")
                    r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={d_str}", auth=auth)
                    if r.status_code == 200: 
                        combined["results"].extend(r.json().get('results', []))
                process_reconciliation(combined)
    except Exception as e:
        st.sidebar.error(f"Stats Error: {e}")

display_sidebar_stats()

# --- 6. MAIN ENGINE ---
if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for r_data in race.get('runners', []):
                    # Simplified logic to prevent errors
                    sp = r_data.get('sp_dec', 1.0)
                    score = 15 if str(r_data.get('form', '')).endswith('1') else 0
                    if score >= 15: # Broadened for testing
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'),
                            "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')),
                            "Odds": float(sp) if sp else 1.0, 
                            "Score": score, "Stake": stake_val,
                            "Result": "Pending", "Pos": "-", "P/L": 0.0
                        })

# --- UI DISPLAY ---
if st.session_state.value_horses:
    st.markdown("### 🏆 Gold Bets")
    for h in st.session_state.value_horses[:3]:
        st.success(f"**{h['Horse']}** ({h['Time']} {h['Course']}) - Score: {h['Score']}")
    
    if st.button("📤 Log Selections"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        updated = pd.concat([ledger, new_df], ignore_index=True)
        conn.update(spreadsheet=GSHEET_URL, data=updated)
        st.success("Logged!")
        st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('course')} - {race.get('off_time', 'Race')}"):
            st.write(pd.DataFrame([{"Horse": r.get('horse'), "Form": r.get('form')} for r in race.get('runners', [])]))
