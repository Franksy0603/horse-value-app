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
    """Loads ledger and forces all names/types to be safe."""
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            if df is not None:
                # Remove extra spaces from headers
                df.columns = [str(c).strip() for c in df.columns]
                # Convert P/L and Stake to numbers immediately, or 0 if they fail
                if 'P/L' in df.columns:
                    df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0.0)
                if 'Stake' in df.columns:
                    df['Stake'] = pd.to_numeric(df['Stake'], errors='coerce').fillna(0.0)
                return df
        except Exception as e:
            st.error(f"Spreadsheet Error: {e}")
    return pd.DataFrame()

# --- 3. RECONCILE LOGIC (Aggressive Name Cleaning) ---
def clean_txt(text):
    if text is None: return ""
    # Remove bracketed info (AW), (IRE), etc.
    text = re.sub(r'\(.*?\)', '', str(text))
    # Remove everything except letters and numbers
    text = re.sub(r'[^A-Za-z0-9\s]', '', text)
    # Upper case and remove double spaces
    return " ".join(text.split()).upper().strip()

def process_reconciliation(data):
    """Matches API results to the Ledger without date-dependency."""
    try:
        results_map = {}
        api_log = []
        
        for race in data.get('results', []):
            course_name = clean_txt(race.get('course', ''))
            for runner in race.get('runners', []):
                horse_name = clean_txt(runner.get('horse', ''))
                pos = str(runner.get('position', ''))
                key = f"{course_name}|{horse_name}"
                results_map[key] = pos
                api_log.append(key)

        df = load_ledger()
        if df.empty: return

        # Ensure settlement columns exist
        for col in ['Pos', 'Result', 'P/L']:
            if col not in df.columns: df[col] = "-"

        match_count = 0
        missed = []

        for i, row in df.iterrows():
            # Check if Result is 'Pending' regardless of case
            res_val = str(row.get('Result', '')).strip().upper()
            if res_val == 'PENDING' or res_val == '-':
                lookup_key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
                
                if lookup_key in results_map:
                    final_pos = results_map[lookup_key]
                    df.at[i, 'Pos'] = final_pos
                    if final_pos == '1':
                        df.at[i, 'Result'] = 'Winner'
                        odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1.0
                        df.at[i, 'P/L'] = float(odds) - 1.0
                    else:
                        df.at[i, 'Result'] = 'Loser'
                        df.at[i, 'P/L'] = -1.0
                    match_count += 1
                else:
                    missed.append(lookup_key)

        if match_count > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.success(f"Successfully settled {match_count} bets!")
            st.rerun()
        else:
            st.warning("No matches found between Ledger and API.")
            with st.expander("🔍 Detailed Matching Log"):
                st.write("**Looking for these (from your Sheet):**")
                st.write(missed[:10])
                st.write("**Found these (from API):**")
                st.write(api_log[:10])

    except Exception as e:
        st.error(f"Reconciliation crashed: {e}")

# --- 4. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10, step=1)

def display_sidebar_stats(s_val):
    try:
        df = load_ledger()
        if not df.empty:
            # Safe math
            profit = (df['P/L'] * df['Stake']).sum()
            invested = df['Stake'].sum()
            
            color = "green" if profit >= 0 else "red"
            st.sidebar.markdown(f"### Profit: :{color}[£{profit:,.2f}]")
            
            c1, c2 = st.sidebar.columns(2)
            c1.metric("Invested", f"£{invested:,.0f}")
            roi = (profit / invested * 100) if invested > 0 else 0
            c2.metric("ROI", f"{roi:.1f}%")
            
            st.sidebar.markdown("---")
            st.sidebar.subheader("🔄 Reconcile")
            
            if st.sidebar.button("🔄 Auto-Sync (Last 2 Days)"):
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                all_results = {"results": []}
                for d in [0, 1]:
                    dt = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
                    r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={dt}", auth=auth)
                    if r.status_code == 200:
                        all_results["results"].extend(r.json().get('results', []))
                process_reconciliation(all_results)
    except Exception as e:
        st.sidebar.error("Stats Error: Check Sheet Columns")

display_sidebar_stats(stake_input)

# --- 5 & 6. SCORING & INTERFACE (Consolidated) ---
def get_best_odds(runner):
    sp = runner.get('sp_dec')
    if sp and str(sp).replace('.','',1).isdigit(): return float(sp)
    prices = [float(e.get('decimal')) for e in runner.get('odds', []) if str(e.get('decimal')).replace('.','',1).isdigit()]
    return max(prices) if prices else 0.0

def get_score(h):
    s = 0
    if str(h.get('form', '')).endswith('1'): s += 15
    try:
        win_pc = float(h.get('trainer_14_days', {}).get('percent', 0))
        if win_pc > 20: s += 15
        elif win_pc > 10: s += 5
    except: pass
    return s

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for runner in race.get('runners', []):
                    odds = get_best_odds(runner)
                    score = get_score(runner)
                    if score >= 20 and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": runner.get('horse'),
                            "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')),
                            "Odds": odds, "Score": score, "Stake": stake_input,
                            "Result": "Pending", "Pos": "-", "P/L": 0.0
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 Top Selections")
    cols = st.columns(min(3, len(st.session_state.value_horses)))
    for i, h in enumerate(st.session_state.value_horses[:3]):
        with cols[i]:
            st.success(f"**{h['Horse']}**\n\n{h['Time']} {h['Course']}\n\nScore: {h['Score']}")

    if st.button("📤 Log to Ledger"):
        ledger = load_ledger()
        new_data = pd.DataFrame(st.session_state.value_horses)
        if not ledger.empty:
            new_data = new_data[~new_data['Horse'].isin(ledger['Horse'])]
        combined = pd.concat([ledger, new_data], ignore_index=True)
        conn.update(spreadsheet=GSHEET_URL, data=combined)
        st.success("Logged!")
        st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('course')} - {race.get('off_time', 'Race')}"):
            st.write(pd.DataFrame([{
                "Horse": r.get('horse'), "Score": get_score(r),
                "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP"
            } for r in race.get('runners', [])]))
