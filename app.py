import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. CONFIGURATION & UI SETUP ---
st.set_page_config(page_title="Value Finder Pro", layout="wide")
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

# Custom CSS for Premium GUI
st.markdown("""
    <style>
    .gold-card {
        background: linear-gradient(135deg, #FFD700 0%, #FDB931 100%);
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #B8860B;
        color: #000 !important;
        text-align: center;
        margin-bottom: 15px;
    }
    .gold-card h2 { margin: 0; font-size: 1.5rem; color: #000; }
    .gold-card p { margin: 5px 0; color: #333; font-weight: bold; }
    .stExpander { border: 1px solid #f0f2f6; border-radius: 8px; margin-bottom: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. HELPERS ---
def clean(text):
    if not text or pd.isna(text): return ""
    t = re.sub(r'\(.*?\)', '', str(text)) 
    t = re.sub(r'[^A-Za-z0-9\s]', '', t)
    return " ".join(t.split()).upper().strip()

# --- 3. DATA CONNECTIONS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except:
    st.sidebar.error("❌ Connection Error")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame()

# --- 4. RECONCILE ENGINE (Direct JSON Query) ---
def sync_results(json_data):
    results_map = {}
    for race in json_data.get('results', []):
        course_key = clean(race.get('course', ''))
        for runner in race.get('runners', []):
            horse_key = clean(runner.get('horse', ''))
            # Map Course|Horse to Position
            results_map[f"{course_key}|{horse_key}"] = str(runner.get('position', ''))

    df = load_ledger()
    if df.empty: return
    
    # Ensure update columns exist
    for col in ['Pos', 'Result', 'P/L']:
        if col not in df.columns: df[col] = "-"

    updates = 0
    for i, row in df.iterrows():
        # Settle any row marked Pending
        if str(row.get('Result', '')).strip().upper() == "PENDING":
            match_key = f"{clean(row.get('Course'))}|{clean(row.get('Horse'))}"
            
            if match_key in results_map:
                final_pos = results_map[match_key]
                df.at[i, 'Pos'] = final_pos
                
                if final_pos == "1":
                    df.at[i, 'Result'] = "Winner"
                    odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1
                    df.at[i, 'P/L'] = odds - 1
                else:
                    df.at[i, 'Result'] = "Loser"
                    df.at[i, 'P/L'] = -1.0
                updates += 1

    if updates > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Settled {updates} Bets!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found in JSON. Check the names in your Sheet.")

# --- 5. SIDEBAR: ROI DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", value=10)

df_stats = load_ledger()
if not df_stats.empty and 'P/L' in df_stats.columns:
    pl = pd.to_numeric(df_stats['P/L'], errors='coerce').fillna(0)
    stk = pd.to_numeric(df_stats.get('Stake', stake_input), errors='coerce').fillna(stake_input)
    
    total_profit = (pl * stk).sum()
    total_invested = stk.sum()
    roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
    
    color = "green" if total_profit >= 0 else "red"
    st.sidebar.markdown(f"### Profit: :{color}[£{total_profit:,.2f}]")
    st.sidebar.metric("Invested", f"£{total_invested:,.0f}")
    st.sidebar.metric("ROI", f"{roi:.1f}%")

st.sidebar.markdown("---")
up_file = st.sidebar.file_uploader("📂 Manual Sync (JSON)", type=["json"])
if up_file and st.sidebar.button("🚀 Sync from File"):
    sync_results(json.load(up_file))

if st.sidebar.button("🔄 Auto Sync (Live)"):
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=HTTPBasicAuth(API_USER, API_PASS))
    if r.status_code == 200: sync_results(r.json())

# --- 6. ANALYSIS & GUI ---
def get_score(h):
    s = 0
    if str(h.get('form', '')).endswith('1'): s += 15
    t = h.get('trainer_14_days', {})
    if isinstance(t, dict):
        try:
            p = t.get('percent')
            if p is not None and float(p) > 15: s += 10
        except: pass 
    return s

st.sidebar.markdown("---")
min_val = st.sidebar.slider("Min Value Score", 0, 50, 20)

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing Racecards..."):
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=HTTPBasicAuth(API_USER, API_PASS))
        if r.status_code == 200:
            cards = r.json().get('racecards', [])
            
            # GOLD VALUE CARDS
            all_value = []
            for race in cards:
                for runner in race.get('runners', []):
                    score = get_score(runner)
                    if score >= min_val:
                        all_value.append({"Horse": runner['horse'], "Course": race['course'], "Score": score, "Time": race.get('off', '')})
            
            if all_value:
                st.subheader("🏆 Gold Value Selections")
                top_bets = sorted(all_value, key=lambda x: x['Score'], reverse=True)[:4]
                cols = st.columns(len(top_bets))
                for idx, v in enumerate(top_bets):
                    cols[idx].markdown(f"""<div class="gold-card"><h2>{v['Horse']}</h2><p>{v['Time']} - {v['Course']}</p><hr><h3>Score: {v['Score']}</h3></div>""", unsafe_allow_html=True)

            # MEETINGS
            st.subheader("📍 Race Meetings")
            for race in cards:
                with st.expander(f"🕒 {race.get('off', '??')} - {race.get('course', 'Unknown')}"):
                    rows = [{"Horse": r['horse'], "Score": get_score(r), "Value": "💎 YES" if get_score(r) >= min_val else ""} for r in race.get('runners', [])]
                    st.table(pd.DataFrame(rows))
