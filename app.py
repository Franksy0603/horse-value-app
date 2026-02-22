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
            if df is not None:
                df.columns = [str(c).strip() for c in df.columns]
                for col in ["P/L", "Stake", "Odds"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
                return df
        except Exception as e:
            st.error(f"⚠️ Sheet Load Error: {e}")
    return pd.DataFrame()

# --- 3. RECONCILE LOGIC (STRONGER CLEANING) ---
def clean_txt(text):
    """Aggressively cleans text to force matches between Sheet and API."""
    if not text: return ""
    text = str(text).upper()
    # Remove bracketed country codes and AW tags (e.g., (IRE), (AW), (GB))
    text = re.sub(r'\(.*?\)', '', text)
    # Remove common extra words that cause mismatches
    text = re.sub(r'\b(AW|PARK|CITY|JUNCTION|ESTUARY|REGIONAL|ALL WEATHER)\b', '', text)
    # Strip everything except A-Z and Numbers
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text.strip()

def process_reconciliation(data):
    try:
        results_map = {}
        api_sample = []
        
        # Build Results Map from the JSON
        for race in data.get('results', []):
            course_raw = race.get('course', '')
            course_clean = clean_txt(course_raw)
            for runner in race.get('runners', []):
                horse_raw = runner.get('horse', '')
                horse_clean = clean_txt(horse_raw)
                key = f"{course_clean}|{horse_clean}"
                results_map[key] = str(runner.get('position', ''))
                api_sample.append(f"{course_raw} | {horse_raw} -> {key}")

        df = load_ledger()
        if df.empty: return

        settled_count = 0
        missed_log = []

        for i, row in df.iterrows():
            res_val = str(row.get('Result', '')).strip().upper()
            # Only process if Result is Pending or blank
            if res_val in ['PENDING', '-', '']:
                l_course = clean_txt(row.get('Course'))
                l_horse = clean_txt(row.get('Horse'))
                lookup_key = f"{l_course}|{l_horse}"
                
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
                    missed_log.append(f"{row.get('Course')} | {row.get('Horse')} -> {lookup_key}")

        if settled_count > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.success(f"✅ Successfully settled {settled_count} bets!")
            st.rerun()
        else:
            st.warning("⚠️ No matches found. Check the diagnostic report below.")
            with st.expander("🔍 Diagnostic Report"):
                st.subheader("Your Ledger (Cleaned Keys)")
                st.write(missed_log[:15])
                st.subheader("API File (Cleaned Keys)")
                st.write(api_sample[:15])

    except Exception as e:
        st.error(f"Reconciliation Error: {e}")

# --- 4. SIDEBAR ---
st.sidebar.header("📊 Dashboard")
stake_val = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats():
    try:
        df = load_ledger()
        if not df.empty:
            profit = (df['P/L'] * df['Stake']).sum()
            invested = df['Stake'].sum()
            color = "green" if profit >= 0 else "red"
            st.sidebar.markdown(f"### Total Profit: :{color}[£{profit:,.2f}]")
            
            # MANUAL RECONCILE TOOLS
            st.sidebar.markdown("---")
            st.sidebar.subheader("🔄 Reconcile")
            
            uploaded_file = st.sidebar.file_uploader("Upload Results JSON", type=["json"])
            if uploaded_file and st.sidebar.button("🚀 Process Upload"):
                process_reconciliation(json.load(uploaded_file))

            if st.sidebar.button("🔄 Auto-Sync (Last 2 Days)"):
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

# --- 5. INTERFACE (RESTORED CLEAN VERSION) ---
if st.button('🚀 Run Analysis'):
    with st.spinner("Finding today's value..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                # Basic Score logic
                for r_data in race.get('runners', []):
                    # Simplified Odds Logic
                    sp = r_data.get('sp_dec')
                    odds = float(sp) if sp and str(sp).replace('.','',1).isdigit() else 1.0
                    
                    # Score Logic
                    score = 0
                    if str(r_data.get('form', '')).endswith('1'): score += 15
                    if float(r_data.get('trainer_14_days', {}).get('percent', 0)) > 15: score += 15
                    
                    if score >= 20 and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'),
                            "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')),
                            "Odds": odds, "Score": score, "Stake": stake_val,
                            "Result": "Pending", "Pos": "-", "P/L": 0.0
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 Gold Bets")
    cols = st.columns(min(3, len(st.session_state.value_horses)))
    for i, h in enumerate(st.session_state.value_horses[:3]):
        with cols[i]:
            st.success(f"**{h['Horse']}**\n\n{h['Time']} {h['Course']}\n\nScore: {h['Score']}")

    if st.button("📤 Log All Selections"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        if not ledger.empty:
            new_df = new_df[~new_df.apply(lambda x: ((ledger['Horse'] == x['Horse']) & (ledger['Course'] == x['Course'])).any(), axis=1)]
        if not new_df.empty:
            updated = pd.concat([ledger, new_df], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Logged!")
            st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('course')} - {race.get('off_time', 'Race')}"):
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'), 
                "Score": 15 if str(r.get('form', '')).endswith('1') else 0,
                "Odds": r.get('sp_dec', 'SP')
            } for r in race.get('runners', [])]))
