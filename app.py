import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# --- 1. SETTINGS & PERSISTENCE ---
API_USER = st.secrets["API_USER"]
API_PASS = st.secrets["API_PASS"]

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Standard Edition")

# Initialize session state for the "Paper Trading" tracker
if 'history' not in st.session_state:
    st.session_state.history = []

# --- 2. CORE LOGIC ---
def odds_to_dec(o):
    try:
        if not o or '/' not in str(o): return 0.0
        n, d = o.split('/')
        return (float(n) / float(d)) + 1.0
    except: return 0.0

def get_score(h, race_going):
    """Calculates score using Standard Tier performance data"""
    s = 0
    res = str(h.get('last_run_result', ''))
    if res == '1': s += 15
    
    t_win = h.get('trainer_win_percentage', 0)
    if t_win > 25: s += 20
    elif t_win > 15: s += 10
    
    horse_best_ground = str(h.get('best_going', '')).lower()
    if race_going and horse_best_ground:
        if str(race_going).lower() in horse_best_ground:
            s += 10 
    return s

def highlight_value(row):
    """Gold highlight for Value bets"""
    if row['Value'] == "💎 YES":
        return ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    return [''] * len(row)

# --- 3. DATA FETCH ---
@st.cache_data(ttl=60)
def get_data():
    # Standard Tier Endpoint
    url = "https://api.theracingapi.com/v1/racecards/standard"
    try:
        r = requests.get(url, auth=HTTPBasicAuth(API_USER.strip(), API_PASS.strip()), timeout=15)
        if r.status_code == 200:
            return r.json().get('racecards', [])
    except: pass
    return []

# --- 4. SIDEBAR & TRACKER ---
st.sidebar.header("⚙️ Strategy Filters")
min_score = st.sidebar.slider("Minimum Horse Score", 0, 50, 20)
only_show_value = st.sidebar.checkbox("Only show 'Value' bets", value=False)

st.sidebar.divider()
st.sidebar.header("📊 Test Week Tracker")
if st.session_state.history:
    df_h = pd.DataFrame(st.session_state.history)
    wins = df_h[df_h['Result'] == 'Win'].shape[0]
    total = df_h.shape[0]
    sr = (wins / total) * 100 if total > 0 else 0
    st.sidebar.metric("Strike Rate", f"{sr:.1f}%")
    if st.sidebar.button("Clear History"):
        st.session_state.history = []
        st.rerun()

# --- 5. MAIN DISPLAY ---
if st.button('🚀 Run Analysis'):
    races = get_data()
    
    if not races:
        st.warning("No data found. Ensure your Standard Tier upgrade is active.")
    else:
        current_time = datetime.now().strftime("%H:%M:%S")
        st.info(f"Last updated at: {current_time}")
        
        all_export_data = [] 
        total_v = 0

        for race in races:
            runners = race.get('runners', [])
            race_going = race.get('going', '')
            
            for r in runners:
                score = get_score(r, race_going)
                odds = r.get('odds', 'N/A')
                dec = odds_to_dec(odds)
                # Value Logic: Score 20+ and Odds 4/1+
                is_v = score >= 20 and dec >= 5.0
                
                if score >= min_score:
                    if only_show_value and not is_v: continue
                    
                    all_export_data.append({
                        "Time": race.get('off_time'),
                        "Course": race.get('course'),
                        "Horse": r.get('horse'),
                        "Score": score,
                        "Odds": odds,
                        "Value": "💎 YES" if is_v else ""
                    })
                    if is_v: total_v += 1

        # Dashboard
        c1, c2, c3 = st.columns(3)
        c1.metric("Meetings", len(races))
        c2.metric("Value Bets", total_v)
        c3.metric("Mode", "Standard Data")

        # Tables with Tracker
        for race in races:
            m_rows = [row for row in all_export_data if row['Course'] == race.get('course') and row['Time'] == race.get('off_time')]
            if m_rows:
                with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')}"):
                    df_display = pd.DataFrame(m_rows)[["Horse", "Score", "Odds", "Value"]]
                    st.dataframe(df_display.style.apply(highlight_value, axis=1), use_container_width=True, hide_index=True)
                    
                    # Quick Log for Testing
                    horse_list = [row['Horse'] for row in m_rows]
                    selected_h = st.selectbox("Log Result for:", ["None"] + horse_list, key=f"sel_{race.get('off_time')}")
                    col_w, col_l = st.columns(2)
                    if selected_h != "None":
                        if col_w.button(f"✅ {selected_h} Won", key=f"w_{selected_h}"):
                            st.session_state.history.append({"Horse": selected_h, "Result": "Win"})
                            st.toast(f"Logged Win for {selected_h}!")
                        if col_l.button(f"❌ {selected_h} Lost", key=f"l_{selected_h}"):
                            st.session_state.history.append({"Horse": selected_h, "Result": "Loss"})
