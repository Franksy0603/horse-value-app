import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime

# --- 1. SETTINGS ---
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

# --- 3. CORE LOGIC ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and sp_val != '-':
        try: return float(sp_val)
        except: pass
    
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list) and len(odds_list) > 0:
        prices = []
        for entry in odds_list:
            d_val = entry.get('decimal')
            if d_val and d_val not in ['-', 'SP']:
                try: prices.append(float(d_val))
                except: pass
        if prices: return max(prices)
    return 0.0

def get_score(h):
    s = 0
    form = str(h.get('form', ''))
    if form and form.endswith('1'): s += 15
    
    t_stats = h.get('trainer_14_days')
    if isinstance(t_stats, dict):
        try:
            t_win = float(t_stats.get('percent', 0))
            if t_win > 25: s += 20
            elif t_win > 15: s += 10
        except: pass
    
    rtf = str(h.get('trainer_rtf', '0')).replace('%', '')
    try:
        if float(rtf) > 50: s += 5
    except: pass
    return s

def get_confidence(score):
    if score >= 35: return "🔥 High"
    if score >= 20: return "✅ Med"
    return "❄️ Low"

def style_table(row):
    styles = [''] * len(row)
    if row.get('Value') == "💎 YES":
        styles = ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    return styles

# --- 4. DATA FETCH ---
@st.cache_data(ttl=60)
def fetch_data():
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    try:
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth, timeout=15)
        data = r.json().get('racecards', [])
        if not data:
            r = requests.get("https://api.theracingapi.com/v1/results", auth=auth, timeout=15)
            data = r.json().get('results', [])
        return data
    except: return []

# --- 5. MAIN INTERFACE ---
if st.button('🚀 Run Analysis'):
    races = fetch_data()
    
    if not races:
        st.warning("No live data found.")
    else:
        for race in races:
            runners = race.get('runners', [])
            course = race.get('course', 'Unknown')
            off_time = race.get('off_time', race.get('off', '00:00'))
            
            race_rows = []
            for r in runners:
                if not r.get('horse'): continue
                
                odds_dec = get_best_odds(r)
                score = get_score(r)
                
                if score < min_score: continue
                
                # Probability Calculation: (Score / Max Possible Score)
                prob_pct = f"{int((score / 50) * 100)}%"
                conf = get_confidence(score)
                is_val = "💎 YES" if (score >= 20 and odds_dec >= 5.0) else ""
                
                if only_show_value and not is_val: continue
                
                race_rows.append({
                    "Horse": r.get('horse'),
                    "Score": score,
                    "Prob %": prob_pct,
                    "Conf": conf,
                    "Odds": f"{int(odds_dec-1)}/1" if odds_dec > 1.0 else "N/A",
                    "Value": is_val
                })
            
            if race_rows:
                with st.expander(f"🕒 {off_time} - {course}"):
                    df = pd.DataFrame(race_rows)
                    st.dataframe(df.style.apply(style_table, axis=1), use_container_width=True, hide_index=True)
