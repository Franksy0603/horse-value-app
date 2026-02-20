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

# --- 2. CORE LOGIC ---
def odds_to_dec(o):
    try:
        if not o or '/' not in str(o): return 0.0
        n, d = o.split('/')
        return (float(n) / float(d)) + 1.0
    except: return 0.0

def get_best_odds(runner):
    """Deep scan for SP or Live prices, including hidden 'off_price'"""
    # 1. Check all possible SP and result price fields
    for field in ['sp', 'starting_price', 'off_price', 'decimal_price']:
        val = runner.get(field)
        if val:
            if isinstance(val, str) and '/' in val: return odds_to_dec(val)
            if isinstance(val, (int, float)) and val > 1.0: return float(val)

    # 2. Check Live Bookie Odds dictionary
    bookies = runner.get('bookmaker_odds', {})
    if isinstance(bookies, dict) and bookies:
        prices = [odds_to_dec(v) for v in bookies.values() if isinstance(v, str) and '/' in v]
        if prices: return max(prices)
    return 0.0

def get_score(h, race_going):
    """Standard Scoring Logic"""
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

def style_results(row):
    """Bolds winners and highlights Value picks in Gold"""
    styles = [''] * len(row)
    # Gold Highlight for Value Picks
    if row['Value'] == "💎 YES":
        styles = ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    # Red/Bold text for the Winner
    if row['Win?'] == "🏆 WINNER":
        styles[0] = 'font-weight: 900; color: #FF4B4B; text-decoration: underline;'
        styles[4] = 'font-weight: 900; color: #FF4B4B;'
    return styles

# --- 3. DATA FETCH ---
@st.cache_data(ttl=60)
def fetch_data():
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    # Try cards, then fall back to results for finished races
    try:
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth, timeout=15)
        data = r.json().get('racecards', [])
        if not data:
            r = requests.get("https://api.theracingapi.com/v1/results", auth=auth, timeout=15)
            data = r.json().get('results', [])
        return data
    except: return []

# --- 4. UI & SIDEBAR ---
st.sidebar.header("⚙️ Strategy Filters")
min_score = st.sidebar.slider("Min Score", 0, 50, 0)
only_show_value = st.sidebar.checkbox("Value Only", value=False)

if st.session_state.history:
    st.sidebar.divider()
    df_h = pd.DataFrame(st.session_state.history)
    wins = len(df_h[df_h['Result'] == 'Win'])
    st.sidebar.metric("Test Week Wins", f"{wins} / {len(df_h)}")

# --- 5. MAIN ---
if st.button('🚀 Run Analysis'):
    races = fetch_data()
    if not races:
        st.warning("No data found for Exeter or other meetings.")
    else:
        st.info(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
        for race in races:
            runners = race.get('runners', [])
            course = race.get('course', 'Unknown')
            off_time = race.get('off_time', '00:00')
            race_going = race.get('going', '')
            
            race_data = []
            total_value = 0
            
            for r in runners:
                if not r.get('horse'): continue
                odds = get_best_odds(r)
                score = get_score(r, race_going)
                is_val = score >= 20 and odds >= 5.0
                
                # Check for Winner
                pos = str(r.get('position', '')).strip()
                is_win = "🏆 WINNER" if pos == "1" else ""
                
                if only_show_value and not is_val: continue
                if score >= min_score:
                    race_data.append({
                        "Horse": r.get('horse'),
                        "Score": score,
                        "Odds": f"{int(odds-1)}/1" if odds > 1.0 else "N/A",
                        "Value": "💎 YES" if is_val else "",
                        "Win?": is_win
                    })
            
            if race_data:
                with st.expander(f"🕒 {off_time} - {course} ({race_going})"):
                    df = pd.DataFrame(race_data)
                    st.dataframe(df.style.apply(style_results, axis=1), use_container_width=True, hide_index=True)
                    
                    # Result Logger
                    h_list = [row['Horse'] for row in race_data]
                    sel = st.selectbox("Log:", ["- Select -"] + h_list, key=f"log_{off_time}_{course}")
                    if sel != "- Select -":
                        c1, c2 = st.columns(2)
                        if c1.button("✅ Win", key=f"w_{sel}"):
                            st.session_state.history.append({"Horse": sel, "Result": "Win"})
                        if c2.button("❌ Loss", key=f"l_{sel}"):
                            st.session_state.history.append({"Horse": sel, "Result": "Loss"})
