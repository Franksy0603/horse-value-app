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

# --- 2. CORE MATH & DEEP SCAN FUNCTIONS ---
def odds_to_dec(o):
    try:
        if not o or '/' not in str(o): return 0.0
        n, d = o.split('/')
        return (float(n) / float(d)) + 1.0
    except: return 0.0

def get_best_odds(runner):
    """Deep scans the bookmaker dictionary to find any available price"""
    # 1. Look for the dictionary of bookies
    bookies = runner.get('bookmaker_odds', {})
    
    # 2. If it's empty, check for common fallback fields
    if not bookies or not isinstance(bookies, dict):
        fallback = runner.get('odds') or runner.get('best_odds') or runner.get('sp_odds')
        if fallback and isinstance(fallback, str):
            return odds_to_dec(fallback)
        return 0.0
    
    decimal_prices = []
    # 3. Loop through every bookmaker entry provided
    for val in bookies.values():
        if isinstance(val, str) and '/' in val:
            dec = odds_to_dec(val)
            if dec > 1.0: decimal_prices.append(dec)
        elif isinstance(val, (int, float)):
            if float(val) > 1.0: decimal_prices.append(float(val))
            
    # 4. Return the highest price found
    return max(decimal_prices) if decimal_prices else 0.0

def get_score(h, race_going):
    """Standard Tier Scoring: Updated for flexible data reading"""
    s = 0
    # 1. Form check (Checks 'form' string or 'last_run_result')
    form = str(h.get('form', h.get('last_run_result', '')))
    if form and form[-1] == '1': s += 15
    
    # 2. Trainer check (handles stats dict or flat field)
    t_stats = h.get('trainer_stats', {})
    t_win = 0
    if isinstance(t_stats, dict):
        t_win = t_stats.get('win_percentage', 0)
    else:
        t_win = h.get('trainer_win_percentage', 0)
        
    if t_win > 25: s += 20
    elif t_win > 15: s += 10
    
    # 3. Ground check
    horse_best = str(h.get('best_going', h.get('going_preference', ''))).lower()
    if race_going and str(race_going).lower() in horse_best:
        s += 10 
    return s

def highlight_value(row):
    """Turns Value Bet rows Gold"""
    if row['Value'] == "💎 YES":
        return ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    return [''] * len(row)

# --- 3. DATA FETCH ---
@st.cache_data(ttl=60)
def get_data():
    url = "https://api.theracingapi.com/v1/racecards/standard"
    try:
        r = requests.get(url, auth=HTTPBasicAuth(API_USER.strip(), API_PASS.strip()), timeout=15)
        if r.status_code == 200:
            return r.json().get('racecards', [])
    except: pass
    return []

# --- 4. SIDEBAR TRACKER ---
st.sidebar.header("⚙️ Strategy Filters")
min_score = st.sidebar.slider("Minimum Horse Score", 0, 50, 0)
only_show_value = st.sidebar.checkbox("Only show 'Value' bets", value=False)

st.sidebar.divider()
st.sidebar.header("📊 Test Week Results")
if st.session_state.history:
    df_h = pd.DataFrame(st.session_state.history)
    wins = df_h[df_h['Result'] == 'Win'].shape[0]
    total = df_h.shape[0]
    sr = (wins / total) * 100 if total > 0 else 0
    st.sidebar.metric("Strike Rate", f"{sr:.1f}%")
    if st.sidebar.button("Clear History"):
        st.session_state.history = []
        st.rerun()

# --- 5. MAIN LOGIC ---
if st.button('🚀 Run Analysis'):
    races = get_data()
    
    if not races:
        st.warning("No data found. Check your API credentials and Tier.")
    else:
        current_time = datetime.now().strftime("%H:%M:%S")
        st.info(f"Last updated at: {current_time}")
        
        all_export_data = [] 
        total_v = 0

        for race in races:
            runners = race.get('runners', [])
            race_going = race.get('going', '')
            
            for r in runners:
                best_dec = get_best_odds(r)
                score = get_score(r, race_going)
                
                # Value Logic: Score 20+ and Odds 5.0 (4/1) or better
                is_v = score >= 20 and best_dec >= 5.0
                
                # Display Odds Formatting
                display_odds = f"{int(best_dec-1)}/1" if best_dec > 1.0 else "N/A"
                
                if score >= min_score:
                    if only_show_value and not is_v: continue
                    
                    all_export_data.append({
                        "Time": race.get('off_time'),
                        "Course": race.get('course'),
                        "Horse": r.get('horse'),
                        "Score": score,
                        "Odds": display_odds,
                        "Value": "💎 YES" if is_v else ""
                    })
                    if is_v: total_v += 1

        # Dashboard Metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Meetings", len(races))
        c2.metric("Value Bets", total_v)
        c3.metric("API Tier", "Standard ✅")

        # Meeting Expanders
        for race in races:
            m_rows = [row for row in all_export_data if row['Course'] == race.get('course') and row['Time'] == race.get('off_time')]
            if m_rows:
                going_label = race.get('going', 'Unknown')
                with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({going_label})"):
                    df_display = pd.DataFrame(m_rows)[["Horse", "Score", "Odds", "Value"]]
                    st.dataframe(df_display.style.apply(highlight_value, axis=1), use_container_width=True, hide_index=True)
                    
                    # Manual Result Logger
                    h_list = [row['Horse'] for row in m_rows]
                    selected_h = st.selectbox("Log Result:", ["- Select Horse -"] + h_list, key=f"log_{race.get('off_time')}_{race.get('course')}")
                    cw, cl = st.columns(2)
                    if selected_h != "- Select Horse -":
                        if cw.button(f"✅ Win", key=f"win_{selected_h}"):
                            st.session_state.history.append({"Horse": selected_h, "Result": "Win"})
                            st.toast(f"Logged Win for {selected_h}!")
                        if cl.button(f"❌ Loss", key=f"loss_{selected_h}"):
                            st.session_state.history.append({"Horse": selected_h, "Result": "Loss"})
                            st.toast(f"Logged Loss for {selected_h}")
