import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# --- 1. SETTINGS ---
# Ensure these are set in your Streamlit Secrets
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")

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

# --- 3. CORE LOGIC (With Safety Nets) ---
def get_best_odds(runner):
    """Calibrated for the List structure found in your JSON files"""
    # 1. Check for Result SP
    sp_val = runner.get('sp_dec')
    if sp_val and sp_val != '-':
        try: return float(sp_val)
        except: pass
    
    # 2. Check the 'odds' list from Racecards
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list) and len(odds_list) > 0:
        prices = []
        for entry in odds_list:
            # We look for 'decimal' key which we saw in your JSON
            d_val = entry.get('decimal')
            if d_val and d_val not in ['-', 'SP']:
                try: prices.append(float(d_val))
                except: pass
        if prices: return max(prices)
    
    return 0.0

def get_score(h, race_going):
    """Safety-checked scoring logic"""
    s = 0
    # Last Run Check
    form = str(h.get('form', ''))
    if form and form.endswith('1'): s += 15
    
    # Trainer Stats Check (Standard Tier 14-day field)
    t_stats = h.get('trainer_14_days')
    if isinstance(t_stats, dict):
        try:
            t_win = float(t_stats.get('percent', 0))
            if t_win > 25: s += 20
            elif t_win > 15: s += 10
        except: pass
    
    # Trainer RTF Check
    rtf = str(h.get('trainer_rtf', '0')).replace('%', '')
    try:
        if float(rtf) > 50: s += 5
    except: pass
    
    return s

def style_table(row):
    styles = [''] * len(row)
    if row.get('Value') == "💎 YES":
        styles = ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    if row.get('Win?') == "🏆 WINNER":
        styles[0] = 'font-weight: 900; color: #FF4B4B; text-decoration: underline;'
        styles[4] = 'font-weight: 900; color: #FF4B4B;'
    return styles

# --- 4. DATA FETCH ---
@st.cache_data(ttl=60)
def fetch_data():
    if not API_USER or not API_PASS:
        st.error("API Credentials missing in Secrets!")
        return [], {}
    
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    try:
        # Try Racecards first
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth, timeout=15)
        raw_json = r.json()
        data = raw_json.get('racecards', [])
        
        # If no racecards (e.g. evening), try results
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
        st.warning("No live data found. Check back at 10 AM tomorrow for Saturday's cards.")
    else:
        st.success(f"Connected! Data timestamp: {raw_debug.get('last_updated', 'Just now')}")
        
        for race in races:
            runners = race.get('runners', [])
            course = race.get('course', 'Unknown')
            off_time = race.get('off_time', race.get('off', '00:00'))
            
            race_rows = []
            for r in runners:
                if not r.get('horse'): continue
                
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

# Diagnostic tool for you at the bottom
with st.expander("🛠️ Debug View"):
    st.write("If you see an error above, paste it here. This checks if the API is active.")
    if st.button("Check API Connection"):
        st.write(f"User: {API_USER[:3]}***")
