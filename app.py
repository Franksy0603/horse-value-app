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
st.title("🏇 Value Finder Pro: Master Ledger")

# --- 2. THE ULTIMATE CLEANER ---
def clean_name(name):
    """Deep cleans names to ensure 'Chelmsford (AW)' matches 'Chelmsford'."""
    if not name or pd.isna(name): return ""
    text = str(name).upper().strip()
    # Remove brackets and everything inside them: (GB), (IRE), (AW), (AUS)
    text = re.sub(r'\(.*?\)', '', text)
    # Remove all non-alphanumeric characters (apostrophes, hyphens, etc)
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    # Collapse multiple spaces into one
    return " ".join(text.split())

# --- 3. SECURE CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Ledger Connected")
except Exception as e:
    st.sidebar.error("❌ Connection Error")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            # Standardize headers to avoid Case errors
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L"])

# --- 4. DATA PROCESSING ENGINE ---
def process_data_and_update(file_data):
    all_positions = {} 
    results_list = file_data.get('results', [])
    
    # 1. Map names from JSON
    for race in results_list:
        course_json = clean_name(race.get('course', '')) 
        for runner in race.get('runners', []):
            horse_json = clean_name(runner.get('horse', ''))
            pos_val = runner.get('position')
            if pos_val is not None:
                all_positions[f"{course_json}|{horse_json}"] = str(pos_val)

    df = load_ledger()
    if 'Pos' not in df.columns: df['Pos'] = "-"
    
    match_count = 0
    # 2. Iterate through Sheet looking for ANY 'Pending' row
    for index, row in df.iterrows():
        # Fuzzy status check
        status = str(row.get('Result', '')).strip().upper()
        if status == "PENDING":
            c_sheet = clean_name(row.get('Course', ''))
            h_sheet = clean_name(row.get('Horse', ''))
            lookup_key = f"{c_sheet}|{h_sheet}"
            
            if lookup_key in all_positions:
                actual_pos = all_positions[lookup_key]
                df.at[index, 'Pos'] = actual_pos
                
                # Settle Bet
                if str(actual_pos) == '1':
                    df.at[index, 'Result'] = 'Winner'
                    odds = pd.to_numeric(row.get('Odds', 1.0), errors='coerce') or 1.0
                    df.at[index, 'P/L'] = odds - 1
                else:
                    df.at[index, 'Result'] = 'Loser'
                    df.at[index, 'P/L'] = -1.0
                match_count += 1
    
    if match_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Successfully updated {match_count} bets!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found. Check the names in your Sheet.")

# --- 5. PERFORMANCE DASHBOARD (RESTORED) ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        # Convert P/L and Stake to numeric for calculations
        df['P/L_Num'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake_Num'] = pd.to_numeric(df.get('Stake', s_val), errors='coerce').fillna(s_val)
        
        total_profit = (df['P/L_Num'] * df['Stake_Num']).sum()
        total_invested = df['Stake_Num'].sum()
        roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
        
        pl_color = "green" if total_profit >= 0 else "red"
        st.sidebar.markdown(f"### Profit: :{pl_color}[£{total_profit:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested:,.0f}")
        c2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        # Reconciliation Controls
        if st.sidebar.button("🔄 Auto Reconcile (Live API)"):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
            if r.status_code == 200: process_data_and_update(r.json())
            else: st.sidebar.error(f"API Locked ({r.status_code})")

        uploaded_file = st.sidebar.file_uploader("📂 Manual JSON Update", type=["json"])
        if uploaded_file and st.sidebar.button("🚀 Sync from File"):
            process_data_and_update(json.load(uploaded_file))
    else:
        st.sidebar.info("Ledger is empty.")

display_sidebar_stats(stake_input)

# --- 6. ANALYSIS LOGIC ---
# (Keep your existing 'Run Analysis' and Score logic here)
