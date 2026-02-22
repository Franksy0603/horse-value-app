import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Ledger & ROI")

# --- 2. THE ULTIMATE CLEANER ---
def clean_name(name):
    if not name or pd.isna(name): return ""
    text = str(name).upper()
    text = re.sub(r'\(.*?\)', '', text) # Removes (GB), (AW), etc.
    text = re.sub(r'[^A-Z0-9\s]', '', text) 
    return " ".join(text.split()).strip()

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
            # Standardize headers to avoid "KeyError"
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L"])

# --- 4. DATA SYNC ENGINE ---
def process_data_and_update(file_data):
    all_positions = {} 
    results_list = file_data.get('results', [])
    
    # Map normalized names to positions from JSON
    for race in results_list:
        course_json = clean_name(race.get('course', '')) 
        for runner in race.get('runners', []):
            horse_json = clean_name(runner.get('horse', ''))
            pos_val = runner.get('position')
            if pos_val:
                all_positions[f"{course_json}|{horse_json}"] = str(pos_val)

    df = load_ledger()
    if 'Pos' not in df.columns: df['Pos'] = "-"
    
    match_count = 0
    for index, row in df.iterrows():
        # Clean the status check to be case-insensitive
        status = str(row.get('Result', '')).strip().upper()
        if status == "PENDING":
            c_sheet = clean_name(row.get('Course', ''))
            h_sheet = clean_name(row.get('Horse', ''))
            lookup_key = f"{c_sheet}|{h_sheet}"
            
            if lookup_key in all_positions:
                actual_pos = all_positions[lookup_key]
                df.at[index, 'Pos'] = actual_pos
                
                # Logic: Winner if Pos is 1
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
        st.sidebar.success(f"✅ Synced {match_count} results!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found in this JSON for 'Pending' horses.")

# --- 5. RESTORED ROI & PERFORMANCE ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_stats(s_val):
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        # Convert columns to numbers for math
        df['PL_NUM'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['STK_NUM'] = pd.to_numeric(df.get('Stake', s_val), errors='coerce').fillna(s_val)
        
        total_profit = (df['PL_NUM'] * df['STK_NUM']).sum()
        total_invested = df['STK_NUM'].sum()
        roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
        
        color = "green" if total_profit >= 0 else "red"
        st.sidebar.markdown(f"### Total Profit: :{color}[£{total_profit:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested:,.0f}")
        c2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        if st.sidebar.button("🔄 Auto Reconcile (Live)"):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
            if r.status_code == 200: process_data_and_update(r.json())
            else: st.sidebar.error("API Locked")

        uploaded = st.sidebar.file_uploader("📂 Manual JSON Update", type=["json"])
        if uploaded and st.sidebar.button("🚀 Sync from File"):
            process_data_and_update(json.load(uploaded))
    else:
        st.sidebar.info("Ledger is empty.")

display_stats(stake_input)

# --- 6. ANALYSIS & LOGGING ---
# ... (Analysis code for finding new horses)
