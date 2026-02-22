import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Ledger Update")

# --- 1. SETTINGS & CONNECTION ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except:
    st.sidebar.error("❌ GSheet Connection Failed")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
        df.columns = [str(c).strip() for c in df.columns]
        return df
    return pd.DataFrame()

# --- 2. SIMPLE NAME CLEANER ---
def clean(text):
    if not text: return ""
    # Just strip suffixes like (GB) and make Uppercase
    return re.sub(r'\(.*?\)', '', str(text)).strip().upper()

# --- 3. THE RECONCILE ENGINE ---
def reconcile_from_json(data):
    # 1. Build a simple lookup of what happened
    results_map = {}
    for race in data.get('results', []):
        course = clean(race.get('course', ''))
        for runner in race.get('runners', []):
            horse = clean(runner.get('horse', ''))
            pos = str(runner.get('position', ''))
            # Key is COURSE|HORSE
            results_map[f"{course}|{horse}"] = pos

    # 2. Update the Ledger
    df = load_ledger()
    if df.empty: return
    
    updated = 0
    for i, row in df.iterrows():
        # Only check horses marked as Pending
        if str(row.get('Result', '')).strip().upper() == "PENDING":
            c_key = clean(row.get('Course', ''))
            h_key = clean(row.get('Horse', ''))
            key = f"{c_key}|{h_key}"
            
            if key in results_map:
                final_pos = results_map[key]
                df.at[i, 'Pos'] = final_pos
                # Determine Win/Loss
                if final_pos == "1":
                    df.at[i, 'Result'] = "Winner"
                    odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1
                    df.at[i, 'P/L'] = odds - 1
                else:
                    df.at[i, 'Result'] = "Loser"
                    df.at[index, 'P/L'] = -1.0
                updated += 1
    
    if updated > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Updated {updated} horses!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found. Ensure horse names in Sheet match the JSON.")

# --- 4. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance")
stake = st.sidebar.number_input("Standard Stake (£)", value=10)

df_stats = load_ledger()
if not df_stats.empty and 'P/L' in df_stats.columns:
    # ROI MATH
    pl = pd.to_numeric(df_stats['P/L'], errors='coerce').fillna(0)
    stk = pd.to_numeric(df_stats.get('Stake', stake), errors='coerce').fillna(stake)
    total_profit = (pl * stk).sum()
    total_invested = stk.sum()
    roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
    
    color = "green" if total_profit >= 0 else "red"
    st.sidebar.markdown(f"### Profit: :{color}[£{total_profit:,.2f}]")
    st.sidebar.metric("Invested", f"£{total_invested:,.0f}")
    st.sidebar.metric("ROI", f"{roi:.1f}%")

st.sidebar.markdown("---")
# SYNC TOOLS
uploaded_file = st.sidebar.file_uploader("Upload Results JSON", type=["json"])
if uploaded_file and st.sidebar.button("🚀 Sync Yesterday's Results"):
    reconcile_from_json(json.load(uploaded_file))

if st.sidebar.button("🔄 Auto Reconcile (Live)"):
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=HTTPBasicAuth(API_USER, API_PASS))
    if r.status_code == 200: reconcile_from_json(r.json())

# --- 5. RUN ANALYSIS (Original Logic) ---
# ... (Analysis code here)
