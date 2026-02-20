import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone
import json

# --- 1. SETTINGS & PERSISTENCE ---
API_USER = st.secrets["API_USER"]
API_PASS = st.secrets["API_PASS"]

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Standard Edition")

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 2. SIDEBAR FILTERS (Fixed Positioning) ---
st.sidebar.header("⚙️ Strategy Filters")
min_score = st.sidebar.slider("Minimum Horse Score", 0, 50, 0)
only_show_value = st.sidebar.checkbox("Only show 'Value' bets", value=False)

if st.session_state.history:
    st.sidebar.divider()
    df_h = pd.DataFrame(st.session_state.history)
    wins = len(df_h[df_h['Result'] == 'Win'])
    st.sidebar.metric("Test Week Wins", f"{wins} / {len(df_h)}")
    if st.sidebar.button("Clear History"):
        st.session_state.history = []
        st.rerun()

# --- 3. CORE LOGIC & DEEP SCAN ---
def odds_to_dec(o):
    try:
        if not o or '/' not in str(o): return 0.0
        n, d = o.split('/')
        return (float(n) / float(d)) + 1.0
    except: return 0.0

def get_best_odds(runner):
    """Deepest possible scan for Standard Tier prices"""
    bookies = runner.get('bookmaker_odds', {})
    if isinstance(bookies, dict) and bookies:
        prices = [odds_to_dec(v) for v in bookies.values() if isinstance(v, str) and '/' in v]
        if prices: return max(prices)
    
    # Comprehensive fallback list for SP and off-market prices
    fallbacks = ['sp', 'starting_price', 'odds', 'decimal_odds', 'off_price', 'traditional_odds', 'last_price']
    for field in fallbacks:
        val = runner.get(field)
        if val:
            if isinstance(val, str) and '/' in val: return odds_to_dec(val)
            if isinstance(val, (int, float)) and val > 1.0: return float(val)
    return 0.0

def get_score(h, race_going):
    """Scores horses based on Form, Trainer Stats, and Going"""
    s = 0
    form = str(h.get('form', h.get('last_run_result', '')))
    if form and form[-1] == '1': s += 15
    
    t_stats = h.get('trainer_stats', {})
    t_win = t_stats.get('win_percentage', h.get('trainer_win_percentage', 0)) if isinstance(t_stats, dict) else 0
    if t_win > 25: s += 20
    elif t_win > 15: s += 10
    
    horse_best = str(h.get('best_going', h.get('going_preference', ''))).lower()
    if race_going and str(race_going).lower() in horse_best: s += 10 
    return s

def style_table(row):
    """Visual cues: Gold for value, Bold Underline for winners"""
    styles = [''] * len(row)
    if row['Value'] == "💎 YES":
        styles = ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    if row['Win?'] == "🏆 WINNER":
        styles[0] = 'font-weight: 900; color: #FF4B4B; text-decoration: underline;'
        styles[4] = 'font-weight: 900; color: #FF4B4B;'
    return styles

# --- 4. DATA FETCH ---
@st.cache_data(ttl=60)
def fetch_data():
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    try:
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth, timeout=15)
        raw_json = r.json()
        data = raw_json.get('racecards', [])
        
        # Automatic switch to results endpoint if cards are empty
        if not data:
            r = requests.get("https://api.theracingapi.com/v1/results", auth=auth, timeout=15)
            raw_json = r.json()
            data = raw_json.get('results', [])
            
        return data, raw_json
    except Exception as e:
        return [], {"error": str(e)}

# --- 5. MAIN INTERFACE ---
if st.button('🚀 Run Analysis'):
    races, raw_debug = fetch_data()
    
    if not races:
        st.warning("No data found. This is normal during late-night or early-morning hours.")
    else:
        # Data Freshness Check
        api_time_str = raw_debug.get('last_updated', datetime.now().strftime('%H:%M:%S'))
        st.info(f"Last API Update: {api_time_str} | Dashboard Refresh: {datetime.now().strftime('%H:%M:%S')}")
        
        for race in races:
            runners = race.get('runners', [])
            course = race.get('course', 'Unknown')
            off_time = race.get('off_time', '00:00')
            race_going = race.get('going', '')
            
            race_rows = []
            for r in runners:
                if not r.get('horse'): continue
                odds_dec = get_best_odds(r)
                score = get_score(r, race_going)
                
                if score < min_score: continue
                
                is_val = "💎 YES" if (score >= 20 and odds_dec >= 5.0) else ""
                pos = str(r.get('position', '')).strip()
                is_win = "🏆 WINNER" if pos == "1" else ""
                
                if only_show_value and not is_val: continue
                
                race_rows.append({
                    "Horse": r.get('horse'),
                    "Score": score,
                    "Odds": f"{int(odds_dec-1)}/1" if odds_dec > 1.0 else "N/A",
                    "Value": is_val,
                    "Win?": is_win
                })
            
            if race_rows:
                with st.expander(f"🕒 {off_time} - {course} ({race_going})"):
                    df = pd.DataFrame(race_rows)
                    st.dataframe(df.style.apply(style_table, axis=1), use_container_width=True, hide_index=True)
                    
                    # Manual Logger for Test Week
                    h_list = [row['Horse'] for row in race_rows]
                    sel = st.selectbox("Log Result:", ["- Select -"] + h_list, key=f"log_{off_time}_{course}")
                    if sel != "- Select -":
                        c1, c2 = st.columns(2)
                        if c1.button("✅ Win", key=f"w_{sel}"):
                            st.session_state.history.append({"Horse": sel, "Result": "Win"})
                            st.toast(f"Logged Win: {sel}")
                        if c2.button("❌ Loss", key=f"l_{sel}"):
                            st.session_state.history.append({"Horse": sel, "Result": "Loss"})
                            st.toast(f"Logged Loss: {sel}")

        # --- 6. DIAGNOSTICS (At bottom) ---
        st.divider()
        with st.expander("🛠️ API Diagnostics (Raw Data Check)"):
            st.write("Examine the raw data fields below if odds show as 'N/A'.")
            if races and len(races) > 0 and len(races[0].get('runners', [])) > 0:
                st.json(races[0]['runners'][0])
            else:
                st.write("No runner data found in this response.")
