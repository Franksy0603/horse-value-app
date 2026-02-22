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
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            if df is not None:
                df.columns = [str(c).strip() for c in df.columns]
                # Defensive numeric conversion
                for col in ["P/L", "Stake", "Odds"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0 if col != "Odds" else 1.0)
                return df
        except Exception as e:
            st.error(f"⚠️ Sheet Load Error: {e}")
    return pd.DataFrame()

# --- 3. SMART RECONCILE LOGIC ---
def clean_txt(text):
    if not text: return ""
    text = str(text).upper()
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\b(AW|PARK|CITY|JUNCTION|ESTUARY|REGIONAL)\b', '', text)
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text.strip()

def process_reconciliation(data):
    """Processes available results and leaves others pending."""
    try:
        results_map = {}
        for race in data.get('results', []):
            course = clean_txt(race.get('course', ''))
            for runner in race.get('runners', []):
                horse = clean_txt(runner.get('horse', ''))
                key = f"{course}|{horse}"
                results_map[key] = str(runner.get('position', ''))

        df = load_ledger()
        if df.empty: return

        settled_count = 0
        still_pending = 0

        for i, row in df.iterrows():
            current_res = str(row.get('Result', '')).strip().upper()
            if current_res in ['PENDING', '-', '']:
                l_key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
                
                if l_key in results_map:
                    pos = results_map[l_key]
                    df.at[i, 'Pos'] = pos
                    if pos == '1':
                        df.at[i, 'Result'] = 'Winner'
                        df.at[i, 'P/L'] = float(row.get('Odds', 1)) - 1.0
                    else:
                        df.at[i, 'Result'] = 'Loser'
                        df.at[i, 'P/L'] = -1.0
                    settled_count += 1
                else:
                    still_pending += 1

        if settled_count > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.success(f"✅ Settled {settled_count} bets.")
            st.rerun()
        else:
            st.warning(f"No results found in API for your {still_pending} pending bets.")

    except Exception as e:
        st.error(f"Reconciliation Error: {e}")

# --- 4. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_val = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats():
    try:
        df = load_ledger()
        if not df.empty:
            profit = (df['P/L'] * df['Stake']).sum()
            invested = df['Stake'].sum()
            color = "green" if profit >= 0 else "red"
            st.sidebar.markdown(f"### Profit: :{color}[£{profit:,.2f}]")
            
            c1, c2 = st.sidebar.columns(2)
            c1.metric("Invested", f"£{invested:,.0f}")
            roi = (profit / invested * 100) if invested > 0 else 0
            c2.metric("ROI", f"{roi:.1f}%")
            
            st.sidebar.markdown("---")
            if st.sidebar.button("🔄 Deep Sync (Last 3 Days)"):
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                combined = {"results": []}
                # Increased lookback to 3 days to catch all weekend results
                for day in range(4):
                    d_str = (datetime.now() - timedelta(days=day)).strftime("%Y-%m-%d")
                    r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={d_str}", auth=auth)
                    if r.status_code == 200: 
                        combined["results"].extend(r.json().get('results', []))
                
                r_live = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
                if r_live.status_code == 200:
                    combined["results"].extend(r_live.json().get('results', []))
                
                process_reconciliation(combined)
    except Exception as e:
        st.sidebar.error(f"Stats Error: {e}")

display_sidebar_stats()

# --- 5. SCORING ENGINE ---
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

# --- 6. MAIN INTERFACE ---
if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for r_data in race.get('runners', []):
                    odds, score = get_best_odds(r_data), get_score(r_data)
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
        cols[i].success(f"**{h['Horse']}**\n\n{h['Time']} {h['Course']}\n\nScore: {h['Score']}")
    
    if st.button("📤 Log Selections"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        if not ledger.empty:
            new_df = new_df[~new_df.apply(lambda x: ((ledger['Horse'] == x['Horse']) & 
                                                      (ledger['Course'] == x['Course']) & 
                                                      (ledger['Date'] == x['Date'])).any(), axis=1)]
        if not new_df.empty:
            updated = pd.concat([ledger, new_df], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success(f"Logged {len(new_df)} selections!")
            st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('course')} - {race.get('off_time', 'Race')}"):
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'), "Score": get_score(r),
                "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP"
            } for r in race.get('runners', [])]))
