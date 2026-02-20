import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# --- 1. SETTINGS ---
API_USER = st.secrets["API_USER"]
API_PASS = st.secrets["API_PASS"]

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Standard Edition")

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 2. SIDEBAR FILTERS ---
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

# --- 3. CORE LOGIC (Calibrated to your JSON) ---
def get_best_odds(runner):
    """Calibrated for Standard Tier List structure"""
    # 1. Check for Starting Price (Results)
    if 'sp_dec' in runner:
        try: return float(runner['sp_dec'])
        except: pass
    
    # 2. Check the 'odds' list (Racecards)
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list) and len(odds_list) > 0:
        prices = []
        for entry in odds_list:
            d_val = entry.get('decimal')
            if d_val and d_val != '-':
                try: prices.append(float(d_val))
                except: pass
        if prices: return max(prices)
    
    return 0.0

def get_score(h, race_going):
    """Scores based on Form and 14-day Trainer Stats"""
    s = 0
    # Form Check
    form = str(h.get('form', ''))
    if form and form[-1] == '1': s += 15
    
    # Trainer Check (Using the 14-day percent found in your JSON)
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        t_win = float(t_stats.get('percent', 0))
        if t_win > 25: s += 20
        elif t_win > 15: s += 10
    
    # RTF Check (Running To Form - extra metric found in your JSON)
    rtf = h.get('trainer_rtf', '0')
    try:
        if float(rtf.replace('%','')) > 50: s += 5
    except: pass
    
    return s

def style_table(row):
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
        if not data:
            r = requests.get("https://api.theracingapi.com/v1/results", auth=auth, timeout=15)
            raw_json = r.json()
            data = raw_json.get('results', [])
        return data, raw_json
    except: return [], {}

# --- 5. MAIN INTERFACE ---
if st.button('🚀 Run Analysis'):
    races, raw_debug = fetch_data()
    if not races:
        st.warning("No data found. Checking morning cards is best.")
    else:
        st.info(f"Last API Update: {raw_debug.get('last_updated', 'N/A')}")
        for race in races:
            runners = race.get('runners', [])
            course = race.get('course', 'Unknown')
            off_time = race.get('off_time', race.get('off', '00:00'))
            
            race_rows = []
            for r in runners:
                odds_dec = get_best_odds(r)
                score = get_score(r, race.get('going', ''))
                
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
                with st.expander(f"🕒 {off_time} - {course}"):
                    df = pd.DataFrame(race_rows)
                    st.dataframe(df.style.apply(style_table, axis=1), use_container_width=True, hide_index=True)
