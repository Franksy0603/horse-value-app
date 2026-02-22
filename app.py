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

# --- 2. THE CLEANER (Essential for Matching) ---
def clean(text):
    if not text or pd.isna(text): return ""
    t = re.sub(r'\(.*?\)', '', str(text)) # Removes (GB), (AUS), etc.
    t = re.sub(r'[^A-Za-z0-9\s]', '', t) # Removes dots/apostrophes
    return " ".join(t.split()).upper().strip()

# --- 3. GOOGLE SHEETS HANDLER ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except:
    st.sidebar.error("❌ Ledger Connection Failed")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
        df.columns = [str(c).strip() for c in df.columns]
        return df
    return pd.DataFrame()

# --- 4. RECONCILE ENGINE (Direct JSON Query) ---
def sync_results(json_data):
    # Create lookup from your specific JSON structure
    results_map = {}
    for race in json_data.get('results', []):
        course_key = clean(race.get('course', ''))
        for runner in race.get('runners', []):
            horse_key = clean(runner.get('horse', ''))
            pos = str(runner.get('position', ''))
            results_map[f"{course_key}|{horse_key}"] = pos

    df = load_ledger()
    if df.empty: return
    
    # Ensure necessary columns exist for the update
    for col in ['Pos', 'Result', 'P/L']:
        if col not in df.columns: df[col] = "-"

    updates = 0
    for i, row in df.iterrows():
        if str(row.get('Result', '')).strip().upper() == "PENDING":
            match_key = f"{clean(row.get('Course'))}|{clean(row.get('Horse'))}"
            
            if match_key in results_map:
                final_pos = results_map[match_key]
                df.at[i, 'Pos'] = final_pos
                
                # Settle Logic
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
        st.sidebar.success(f"✅ Updated {updates} Results!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found in JSON for Pending horses.")

# --- 5. SIDEBAR: PERFORMANCE & SYNC ---
st.sidebar.header("📊 Performance")
stake_input = st.sidebar.number_input("Standard Stake (£)", value=10)

df_ledger = load_ledger()
if not df_ledger.empty and 'P/L' in df_ledger.columns:
    pl = pd.to_numeric(df_ledger['P/L'], errors='coerce').fillna(0)
    stk = pd.to_numeric(df_ledger.get('Stake', stake_input), errors='coerce').fillna(stake_input)
    
    total_prof = (pl * stk).sum()
    total_inst = stk.sum()
    roi = (total_prof / total_inst * 100) if total_inst > 0 else 0
    
    color = "green" if total_prof >= 0 else "red"
    st.sidebar.markdown(f"### Profit: :{color}[£{total_prof:,.2f}]")
    st.sidebar.metric("Invested", f"£{total_inst:,.0f}")
    st.sidebar.metric("ROI", f"{roi:.1f}%")

st.sidebar.markdown("---")
# Manual Sync
up_file = st.sidebar.file_uploader("📂 Upload JSON", type=["json"])
if up_file and st.sidebar.button("🚀 Sync Yesterday's Results"):
    sync_results(json.load(up_file))

# Auto Sync
if st.sidebar.button("🔄 Auto Sync (Live)"):
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=HTTPBasicAuth(API_USER, API_PASS))
    if r.status_code == 200: sync_results(r.json())

# --- 6. ANALYSIS ENGINE (Meetings & Value) ---
def get_score(h):
    s = 0
    if str(h.get('form', '')).endswith('1'): s += 15
    t = h.get('trainer_14_days', {})
    if isinstance(t, dict) and float(t.get('percent', 0)) > 15: s += 10
    return s

st.sidebar.markdown("---")
min_val = st.sidebar.slider("Min Value Score", 0, 50, 20)

if st.button('🚀 Run Analysis'):
    with st.spinner("Finding value..."):
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=HTTPBasicAuth(API_USER, API_PASS))
        if r.status_code == 200:
            cards = r.json().get('racecards', [])
            
            # Highlight Gold Bets
            all_value = []
            for race in cards:
                for runner in race.get('runners', []):
                    score = get_score(runner)
                    if score >= min_val:
                        all_value.append({"Horse": runner['horse'], "Course": race['course'], "Score": score})
            
            if all_value:
                st.subheader("🏆 Gold Value Selections")
                cols = st.columns(len(all_value[:4]))
                for idx, v in enumerate(all_value[:4]):
                    cols[idx].metric(v['Horse'], f"Score: {v['Score']}", v['Course'])

            # Show Full Meetings
            for race in cards:
                with st.expander(f"🕒 {race['off']} - {race['course']}"):
                    rows = []
                    for r in race.get('runners', []):
                        s = get_score(r)
                        rows.append({
                            "Horse": r['horse'],
                            "Score": s,
                            "Value": "💎 YES" if s >= min_val else ""
                        })
                    st.table(pd.DataFrame(rows))
