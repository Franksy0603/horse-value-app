import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# --- 1. SETTINGS ---
API_USER = "DIHpCLFafv4Lr6XHNFfUDhzk"
API_PASS = "JIoYBHF8cbJjnjiBkV5XzuUg"

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro")

# --- 2. MATH FUNCTIONS ---
def odds_to_dec(o):
    try:
        if not o or '/' not in str(o): return 0.0
        n, d = o.split('/')
        return (float(n) / float(d)) + 1.0
    except: return 0.0

def get_score(h):
    s = 0
    res = str(h.get('last_run_result', ''))
    if res == '1': s += 20
    if h.get('trainer_win_percentage', 0) > 15: s += 15
    return s

# --- 3. DATA FETCH FUNCTION (Must be above the button!) ---
@st.cache_data(ttl=60)
def get_data():
    url = "https://api.theracingapi.com/v1/racecards/basic"
    try:
        r = requests.get(
            url, 
            auth=HTTPBasicAuth(API_USER.strip(), API_PASS.strip()), 
            timeout=15
        )
        if r.status_code == 200:
            return r.json().get('racecards', [])
    except: pass
    return []

# --- 4. SIDEBAR ---
st.sidebar.header("⚙️ Strategy Filters")
min_score = st.sidebar.slider("Minimum Horse Score", 0, 35, 0) # Set to 0 to ensure we see data
only_show_value = st.sidebar.checkbox("Only show 'Value' bets", value=False)

# --- 5. MAIN DISPLAY ---
if st.button('🚀 Run Analysis'):
    races = get_data()
    
    if not races:
        st.warning("No data found. Check your API connection.")
    else:
        total_value_bets = 0
        all_export_data = []  # List to hold horses for the CSV
        
        # 1. SCAN DATA
        for race in races:
            for r in race.get('runners', []):
                score = get_score(r)
                odds = r.get('odds', 'N/A')
                dec = odds_to_dec(odds)
                is_v = score >= 20 and dec >= 5.0
                
                # Only add to CSV if they meet your sidebar 'Minimum Score'
                if score >= min_score:
                    if only_show_value and not is_v:
                        continue
                    
                    # Prepare the row for CSV
                    all_export_data.append({
                        "Time": race.get('off_time'),
                        "Course": race.get('course'),
                        "Horse": r.get('horse'),
                        "Score": score,
                        "Odds": odds,
                        "Is Value": "YES" if is_v else "NO"
                    })
                    if is_v: total_value_bets += 1

        # 2. DASHBOARD METRICS
        has_odds = any(r.get('odds') for race in races for r in race.get('runners', []))
        c1, c2, c3 = st.columns(3)
        c1.metric("Meetings", len(races))
        c2.metric("Value Bets", total_value_bets)
        c3.metric("API Status", "✅ LIVE" if has_odds else "⚠️ NO ODDS")

        # 3. DOWNLOAD BUTTON
        if all_export_data:
            df_export = pd.DataFrame(all_export_data)
            csv = df_export.to_csv(index=False).encode('utf-8')
            
            # Create a timestamped filename
            now = datetime.now().strftime("%Y-%m-%d_%H%M")
            file_name_with_date = f"selections_{now}.csv"
            
            st.download_button(
                label="📥 Download Selections to CSV",
                data=csv,
                file_name=file_name_with_date,
                mime='text/csv',
            )
            st.divider()

        # 4. DISPLAY TABLES
        for race in races:
            runners = race.get('runners', [])
            meeting_rows = [row for row in all_export_data if row['Course'] == race.get('course') and row['Time'] == race.get('off_time')]
            
            if meeting_rows:
                label = f"🕒 {race.get('off_time', '??')} - {race.get('course', 'Meeting')}"
                with st.expander(label):
                    st.table(pd.DataFrame(meeting_rows)[["Horse", "Score", "Odds", "Is Value"]])