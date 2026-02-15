import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# --- 1. SETTINGS (CLOUD VERSION) ---
API_USER = st.secrets["API_USER"]
API_PASS = st.secrets["API_PASS"]

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro")

# --- 2. MATH & HIGHLIGHTING FUNCTIONS ---
def odds_to_dec(o):
    try:
        if not o or '/' not in str(o): return 0.0
        n, d = o.split('/')
        return (float(n) / float(d)) + 1.0
    except: return 0.0

def get_score(h, race_going):
    """Upgraded Scoring: Includes Trainer Form and Ground Conditions"""
    s = 0
    # 1. Last Run Logic
    res = str(h.get('last_run_result', ''))
    if res == '1': s += 15
    
    # 2. Trainer Form (Win % over 15 is good, over 25 is elite)
    t_win = h.get('trainer_win_percentage', 0)
    if t_win > 25: s += 20
    elif t_win > 15: s += 10
    
    # 3. Ground Conditions (Does the horse like the current 'Going'?)
    horse_best_ground = str(h.get('best_going', '')).lower()
    if race_going and horse_best_ground:
        if str(race_going).lower() in horse_best_ground:
            s += 10 
    return s

def highlight_value(row):
    """Applies a Gold background to Value bets"""
    return ['background-color: #FFD700; color: black; font-weight: bold' if row['Value'] == "💎 YES" else '' for _ in row]

# --- 3. DATA FETCH FUNCTION ---
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
min_score = st.sidebar.slider("Minimum Horse Score", 0, 50, 15)
only_show_value = st.sidebar.checkbox("Only show 'Value' bets", value=False)

# --- 5. MAIN DISPLAY ---
if st.button('🚀 Run Analysis'):
    races = get_data()
    
    if not races:
        st.warning("No data found. Check your API connection.")
    else:
        # 1. TIMESTAMP & INITIALIZATION
        current_time = datetime.now().strftime("%H:%M:%S")
        st.info(f"Last updated at: {current_time}")
        
        total_value_bets = 0
        all_export_data = [] 
        
        # 2. SCAN DATA
        for race in races:
            runners = race.get('runners', [])
            race_going = race.get('going', '')
            
            for r in runners:
                score = get_score(r, race_going)
                odds = r.get('odds', 'N/A')
                dec = odds_to_dec(odds)
                is_v = score >= 20 and dec >= 5.0
                
                if score >= min_score:
                    if only_show_value and not is_v:
                        continue
                    
                    all_export_data.append({
                        "Time": race.get('off_time'),
                        "Course": race.get('course'),
                        "Going": race_going,
                        "Horse": r.get('horse'),
                        "Score": score,
                        "Odds": odds,
                        "Is Value": "YES" if is_v else "NO"
                    })
                    if is_v: total_value_bets += 1

        # 3. DASHBOARD METRICS
        has_odds = any(r.get('odds') for race in races for r in race.get('runners', []))
        c1, c2, c3 = st.columns(3)
        c1.metric("Meetings Loaded", len(races))
        c2.metric("Value Bets Found", total_value_bets)
        c3.metric("API Status", "✅ LIVE" if has_odds else "⚠️ NO ODDS")

        if not has_odds:
            st.error("The API is currently not sending odds data to your account.")

        # 4. DOWNLOAD BUTTON
        if all_export_data:
            df_export = pd.DataFrame(all_export_data)
            csv = df_export.to_csv(index=False).encode('utf-8')
            now_file = datetime.now().strftime("%Y-%m-%d_%H%M")
            st.download_button(
                label="📥 Download Selections to CSV",
                data=csv,
                file_name=f"selections_{now_file}.csv",
                mime='text/csv',
            )
            st.divider()

        # 5. DISPLAY TABLES WITH HIGHLIGHTING
        for race in races:
            meeting_rows = [row for row in all_export_data if row['Course'] == race.get('course') and row['Time'] == race.get('off_time')]
            
            if meeting_rows:
                # Prepare display dataframe
                df_display = pd.DataFrame(meeting_rows)[["Horse", "Score", "Odds", "Is Value"]]
                df_display.columns = ["Horse", "Score", "Odds", "Value"]
                df_display['Value'] = df_display['Value'].map({'YES': '💎 YES', 'NO': ''})

                # Create Expandable Meeting Section
                label = f"🕒 {race.get('off_time')} - {race.get('course')} ({race.get('going', 'Unknown')})"
                with st.expander(label):
                    # Show dataframe with Gold Highlighting
                    st.dataframe(
                        df_display.style.apply(highlight_value, axis=1), 
                        use_container_width=True,
                        hide_index=True
                    )
