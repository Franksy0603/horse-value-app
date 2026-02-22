import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Ledger & Results")

# --- 1. SETTINGS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except:
    st.sidebar.error("❌ Connection Error")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
        df.columns = [str(c).strip() for c in df.columns]
        return df
    return pd.DataFrame()

# --- 2. THE CLEANER ---
def clean(text):
    if not text: return ""
    # Remove (GB), (IRE) etc, remove non-letters, make uppercase
    t = re.sub(r'\(.*?\)', '', str(text))
    t = re.sub(r'[^A-Za-z0-9\s]', '', t)
    return " ".join(t.split()).upper()

# --- 3. THE RECONCILE ENGINE ---
def run_sync(data):
    # Create the dictionary from JSON
    results_map = {}
    for race in data.get('results', []):
        c_name = clean(race.get('course', ''))
        for runner in race.get('runners', []):
            h_name = clean(runner.get('horse', ''))
            # Store the position as a string
            results_map[f"{c_name}|{h_name}"] = str(runner.get('position', ''))

    df = load_ledger()
    if df.empty: return

    # Ensure 'Pos' and 'P/L' columns exist
    if 'Pos' not in df.columns: df['Pos'] = "-"
    if 'P/L' not in df.columns: df['P/L'] = 0.0

    count = 0
    for i, row in df.iterrows():
        # Check for 'Pending' rows
        if str(row.get('Result', '')).strip().upper() == "PENDING":
            key = f"{clean(row.get('Course'))}|{clean(row.get('Horse'))}"
            
            if key in results_map:
                pos = results_map[key]
                df.at[i, 'Pos'] = pos  # <--- HERE IS THE POSITION ADDITION
                
                if pos == "1":
                    df.at[i, 'Result'] = "Winner"
                    odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1
                    df.at[i, 'P/L'] = odds - 1
                else:
                    df.at[i, 'Result'] = "Loser"
                    df.at[i, 'P/L'] = -1.0
                count += 1

    if count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Updated {count} horses!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found. Ensure horse names match exactly.")

# --- 4. DASHBOARD SIDEBAR ---
st.sidebar.header("📊 Performance Dashboard")
stake_val = st.sidebar.number_input("Standard Stake (£)", value=10)

df_stats = load_ledger()
if not df_stats.empty and 'P/L' in df_stats.columns:
    # ROI & Profit Calculation
    pl_col = pd.to_numeric(df_stats['P/L'], errors='coerce').fillna(0)
    stk_col = pd.to_numeric(df_stats.get('Stake', stake_val), errors='coerce').fillna(stake_val)
    
    total_prof = (pl_col * stk_col).sum()
    total_inst = stk_col.sum()
    roi = (total_prof / total_inst * 100) if total_inst > 0 else 0
    
    color = "green" if total_prof >= 0 else "red"
    st.sidebar.markdown(f"### Total Profit: :{color}[£{total_prof:,.2f}]")
    st.sidebar.metric("Invested", f"£{total_inst:,.0f}")
    st.sidebar.metric("ROI", f"{roi:.1f}%")

st.sidebar.markdown("---")
# UPLOAD TOOL
up = st.sidebar.file_uploader("Upload JSON", type=["json"])
if up and st.sidebar.button("🚀 Update Winners & Positions"):
    run_sync(json.load(up))

if st.sidebar.button("🔄 Auto Sync (Live)"):
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=HTTPBasicAuth(API_USER, API_PASS))
    if r.status_code == 200: run_sync(r.json())

# --- 5. ANALYSIS ENGINE (Your Original Logic) ---
# ... [Original 'Run Analysis' code follows here]
