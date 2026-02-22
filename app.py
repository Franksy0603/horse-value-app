import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Value Finder Pro", layout="wide")
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

# Custom CSS for the "Gold Card" look
st.markdown("""
    <style>
    .gold-card {
        background: linear-gradient(135deg, #ffd700 0%, #ffae00 100%);
        padding: 25px;
        border-radius: 15px;
        border: 2px solid #b8860b;
        color: #000000 !important;
        text-align: center;
        box-shadow: 4px 4px 15px rgba(0,0,0,0.2);
        margin-bottom: 20px;
    }
    .gold-card h2, .gold-card p { color: #000000 !important; margin: 5px 0; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. THE CLEANER ---
def clean(text):
    if not text or pd.isna(text): return ""
    t = re.sub(r'\(.*?\)', '', str(text)) 
    t = re.sub(r'[^A-Za-z0-9\s]', '', t)
    return " ".join(t.split()).upper().strip()

# --- 3. GOOGLE SHEETS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except:
    st.sidebar.error("❌ Ledger Connection Failed")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame()

# --- 4. RECONCILE ENGINE (With Date Filtering) ---
def sync_results(json_data):
    results_map = {}
    json_date = ""
    
    # 1. Map Results and capture the date from the JSON
    results_list = json_data.get('results', [])
    if results_list:
        json_date = results_list[0].get('date', '') # Expects "YYYY-MM-DD"
    
    for race in results_list:
        course_key = clean(race.get('course', ''))
        for runner in race.get('runners', []):
            horse_key = clean(runner.get('horse', ''))
            results_map[f"{course_key}|{horse_key}"] = str(runner.get('position', ''))

    df = load_ledger()
    if df.empty: return
    
    for col in ['Pos', 'Result', 'P/L']:
        if col not in df.columns: df[col] = "-"

    updates = 0
    for i, row in df.iterrows():
        # ONLY reconcile if Status is Pending AND Date matches the JSON date
        sheet_date = str(row.get('Date', ''))
        if str(row.get('Result', '')).strip().upper() == "PENDING" and sheet_date == json_date:
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
        st.sidebar.success(f"✅ Updated {updates} Results for {json_date}!")
        st.rerun()
    else:
        st.sidebar.warning(f"No Pending matches found for date: {json_date}")

# --- 5. SIDEBAR: ROI & PERFORMANCE ---
st.sidebar.header("📊 Performance")
stake_input = st.sidebar.number_input("Standard Stake (£)", value=10)

df_ledger = load_ledger()
if not df_ledger.empty and 'P/L' in df_ledger.columns:
    pl = pd.to_numeric(df_ledger['P/L'], errors='coerce').fillna(0)
    stk = pd.to_numeric(df_ledger.get('Stake', stake_input), errors='coerce').fillna(stake_input)
    total_profit = (pl * stk).sum()
    total_inst = stk.sum()
    roi = (total_profit / total_inst * 100) if total_inst > 0 else 0
    
    color = "green" if total_profit >= 0 else "red"
    st.sidebar.markdown(f"### Profit: :{color}[£{total_profit:,.2f}]")
    st.sidebar.metric("Invested", f"£{total_invested:,.0f}" if 'total_invested' in locals() else f"£{total_inst:,.0f}")
    st.sidebar.metric("ROI", f"{roi:.1f}%")

st.sidebar.markdown("---")
up_file = st.sidebar.file_uploader("📂 Upload JSON", type=["json"])
if up_file and st.sidebar.button("🚀 Sync Results"):
    sync_results(json.load(up_file))

if st.sidebar.button("🔄 Auto Sync (Live)"):
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=HTTPBasicAuth(API_USER, API_PASS))
    if r.status_code == 200: sync_results(r.json())

# --- 6. ANALYSIS ENGINE ---
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
    with st.spinner("Finding value..."):
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=HTTPBasicAuth(API_USER, API_PASS))
        if r.status_code == 200:
            cards = r.json().get('racecards', [])
            
            # --- RESTORED GOLD CARDS ---
            all_value = []
            for race in cards:
                for runner in race.get('runners', []):
                    score = get_score(runner)
                    if score >= min_val:
                        all_value.append({
                            "Horse": runner['horse'], 
                            "Course": race['course'], 
                            "Score": score, 
                            "Time": race.get('off', '??')
                        })
            
            if all_value:
                st.subheader("🏆 Gold Value Selections")
                top_bets = sorted(all_value, key=lambda x: x['Score'], reverse=True)[:4]
                cols = st.columns(len(top_bets))
                for idx, v in enumerate(top_bets):
                    with cols[idx]:
                        st.markdown(f"""
                            <div class="gold-card">
                                <h2>{v['Horse']}</h2>
                                <p><b>{v['Time']} - {v['Course']}</b></p>
                                <hr style="border: 1px solid #b8860b;">
                                <h3>Score: {v['Score']}</h3>
                            </div>
                            """, unsafe_allow_html=True)

            # --- MEETINGS TABLE ---
            for race in cards:
                with st.expander(f"🕒 {race.get('off', '??')} - {race.get('course', 'Unknown')}"):
                    rows = [{"Horse": r['horse'], "Score": get_score(r), "Value": "💎 YES" if get_score(r) >= min_val else ""} for r in race.get('runners', [])]
                    st.table(pd.DataFrame(rows))
