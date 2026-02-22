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
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Time"])

# --- 3. RECONCILE LOGIC ---
def clean_txt(text):
    if not text: return ""
    return re.sub(r'\(.*?\)', '', str(text)).strip().upper()

def process_reconciliation(data):
    results_map = {}
    for race in data.get('results', []):
        course = clean_txt(race.get('course', ''))
        for runner in race.get('runners', []):
            horse = clean_txt(runner.get('horse', ''))
            results_map[f"{course}|{horse}"] = str(runner.get('position', ''))

    df = load_ledger()
    if df.empty: return

    match_count = 0
    for i, row in df.iterrows():
        if str(row.get('Result', '')).strip().title() == 'Pending':
            key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
            if key in results_map:
                pos = results_map[key]
                df.at[i, 'Pos'] = pos
                if pos == '1':
                    df.at[i, 'Result'] = 'Winner'
                    odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1
                    df.at[i, 'P/L'] = odds - 1
                else:
                    df.at[i, 'Result'] = 'Loser'
                    df.at[i, 'P/L'] = -1.0
                match_count += 1

    if match_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Settled {match_count} bets!")
        st.rerun()

# --- 4. SIDEBAR DASHBOARD (Corrected ROI Math) ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10, step=1)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty:
        # Convert P/L and Stake to numeric, handling empty strings or symbols
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake'] = pd.to_numeric(df['Stake'], errors='coerce').fillna(s_val)
        
        # MATH FIX: (P/L Multiplier * Stake) = Cash Profit
        total_profit = (df['P/L'] * df['Stake']).sum()
        total_invested = df['Stake'].sum()
        
        pl_color = "green" if total_profit >= 0 else "red"
        st.sidebar.markdown(f"### Total Profit: :{pl_color}[£{total_profit:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested:,.0f}")
        if total_invested > 0:
            roi = (total_profit / total_invested) * 100
            c2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔄 Reconcile Results")
        uploaded_file = st.sidebar.file_uploader("Upload Results JSON", type=["json"])
        if uploaded_file and st.sidebar.button("🚀 Sync Uploaded File"):
            process_reconciliation(json.load(uploaded_file))
        
        if st.sidebar.button("🔄 Auto Reconcile (Live)"):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
            if r.status_code == 200: process_reconciliation(r.json())
    else:
        st.sidebar.info("Ledger is empty.")

display_sidebar_stats(stake_input)

# --- 5. SCORING ENGINE ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and str(sp_val).replace('.','',1).isdigit(): return float(sp_val)
    return 0.0

def get_score(h):
    s = 0
    if str(h.get('form', '')).endswith('1'): s += 15
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            win_pc = pd.to_numeric(t_stats.get('percent', 0), errors='coerce') or 0
            if win_pc > 20: s += 15
            elif win_pc > 10: s += 5
        except: pass
    return s

# --- 6. MAIN INTERFACE ---
st.sidebar.markdown("---")
min_score = st.sidebar.slider("Min Value Score", 0, 50, 20, 5)

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing today's value..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            races = r.json().get('racecards', [])
            st.session_state.all_races = races
            st.session_state.value_horses = []
            for race in races:
                for r_data in race.get('runners', []):
                    odds = get_best_odds(r_data)
                    score = get_score(r_data)
                    if score >= min_score and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'),
                            "Course": race.get('course'),
                            "Odds": odds,
                            "Score": score,
                            "Stake": stake_input,
                            "Result": "Pending",
                            "Pos": "-",
                            "P/L": 0.0,
                            "Time": race.get('off_time', '')
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 GOLD VALUE BETS")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            st.markdown(f"""
            <div style="background-color:#FFD700; padding:20px; border-radius:10px; border:2px solid #DAA520; text-align:center; color:#000;">
                <h2 style="margin:0; color:#000;">{h['Horse']}</h2>
                <p style="margin:5px 0; font-size:16px;"><b>{h['Time']} - {h['Course']}</b></p>
                <hr style="border-top: 1px solid #DAA520;">
                <p style="font-size:20px; margin:5px;"><b>Score: {h['Score']}</b></p>
                <p style="font-size:18px; margin:0;">Odds: {int(h['Odds']-1) if h['Odds'] > 1 else 'SP'}/1</p>
            </div>
            """, unsafe_allow_html=True)

    if st.button("📤 LOG ALL SELECTIONS TO GOOGLE SHEETS"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        # Force order: Date, Horse, Course, Odds, Score, Stake, Result, Pos, P/L, Time
        cols_order = ["Date", "Horse", "Course", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Time"]
        new_df = new_df[cols_order]
        updated_df = pd.concat([ledger, new_df], ignore_index=True)
        conn.update(spreadsheet=GSHEET_URL, data=updated_df)
        st.balloons()
        st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', '')} - {race.get('course')}"):
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'),
                "Score": get_score(r),
                "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP",
                "Value": "💎 YES" if (get_score(r) >= min_score and get_best_odds(r) >= 5.0) else ""
            } for r in race.get('runners', [])]))
