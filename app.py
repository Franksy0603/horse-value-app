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
st.title("🏇 Value Finder Pro: Master Sync")

# --- 2. THE ULTIMATE CLEANER ---
def clean_name(name):
    """Normalizes names by removing brackets, punctuation, and extra spaces."""
    if not name or pd.isna(name): return ""
    text = str(name).upper()
    # Remove everything in brackets: "(GB)", "(IRE)", "(AW)"
    text = re.sub(r'\(.*?\)', '', text)
    # Remove non-alphanumeric characters
    text = re.sub(r'[^A-Z0-9\s]', '', text)
    return " ".join(text.split()).strip()

# --- 3. SECURE CONNECTION ---
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
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L"])

# --- 4. DATA PROCESSING ENGINE ---
def process_data_and_update(file_data):
    all_positions = {} 
    results_list = file_data.get('results', [])
    
    # 1. Map normalized names to positions from JSON
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
    # 2. Match across ANY row marked 'Pending' (Case-insensitive)
    for index, row in df.iterrows():
        status = str(row.get('Result', '')).strip().upper()
        if status == "PENDING":
            c_sheet = clean_name(row.get('Course', ''))
            h_sheet = clean_name(row.get('Horse', ''))
            lookup_key = f"{c_sheet}|{h_sheet}"
            
            if lookup_key in all_positions:
                actual_pos = all_positions[lookup_key]
                df.at[index, 'Pos'] = actual_pos
                
                # Update Result and P/L
                if str(actual_pos) == '1':
                    df.at[index, 'Result'] = 'Winner'
                    odds = pd.to_numeric(row['Odds'], errors='coerce') or 1.0
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
        st.sidebar.warning("No matches found. Showing Debug View below...")
        # DEBUG VIEW: Shows what the script is trying to match
        with st.expander("🔍 Debugging: Why did it fail?"):
            st.write("Horses in your Sheet marked 'Pending':")
            pending_df = df[df['Result'].str.strip().str.upper() == "PENDING"]
            st.write([f"{clean_name(r['Course'])} | {clean_name(r['Horse'])}" for _, r in pending_df.iterrows()])
            st.write("Horses found in your JSON:")
            st.write(list(all_positions.keys())[:10]) # Show first 10

# --- 5. PERFORMANCE DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        # Restore ROI and Profit Math
        df['P/L_Num'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake_Num'] = pd.to_numeric(df.get('Stake', s_val), errors='coerce').fillna(s_val)
        
        total_profit = (df['P/L_Num'] * df['Stake_Num']).sum()
        total_invested = df['Stake_Num'].sum()
        roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
        
        color = "green" if total_profit >= 0 else "red"
        st.sidebar.markdown(f"### Profit: :{color}[£{total_profit:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested:,.0f}")
        c2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        if st.sidebar.button("🔄 Auto Reconcile (Live API)"):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
            if r.status_code == 200: process_data_and_update(r.json())
            else: st.sidebar.error(f"API Locked (Code {r.status_code})")

        uploaded_file = st.sidebar.file_uploader("📂 Manual JSON Update", type=["json"])
        if uploaded_file and st.sidebar.button("🚀 Sync from File"):
            process_data_and_update(json.load(uploaded_file))
    else:
        st.sidebar.info("Ledger is empty.")

display_sidebar_stats(stake_input)

# --- 6. ANALYSIS & LOGGING (Rest of your original script) ---
# ... (Run Analysis button and Logging logic remains the same)
