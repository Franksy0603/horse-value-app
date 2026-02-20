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

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 2. CORE MATH & PRICE SCANNER ---
def odds_to_dec(o):
    try:
        if not o or '/' not in str(o): return 0.0
        n, d = o.split('/')
        return (float(n) / float(d)) + 1.0
    except: return 0.0

def get_best_odds(runner):
    """Deep scans for Starting Price (SP) for finished races"""
    # 1. Check for SP (Starting Price) - priority for results
    sp_fields = ['sp', 'starting_price', 'sp_decimal']
    for field in sp_fields:
        val = runner.get(field)
        if val:
            if isinstance(val, str) and '/' in val: return odds_to_dec(val)
            if isinstance(val, (int, float)) and val > 1.0: return float(val)

    # 2. Check Bookmaker Dictionary (Live Prices)
    bookies = runner.get('bookmaker_odds', {})
    if isinstance(bookies, dict) and bookies:
        decimal_prices = []
        for v in bookies.values():
            if isinstance(v, str) and '/' in v:
                dec = odds_to_dec(v)
                if dec > 1.0: decimal_prices.append(dec)
        if decimal_prices: return max(decimal_prices)
    return 0.0

def get_score(h, race_going):
    """Standard Tier Scoring"""
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

def style_rows(row):
    """Highlights Value in Gold and Winners in Bold"""
    styles = [''] * len(row)
    # Gold Highlight for Value Picks
    if row['Value'] == "💎 YES":
        styles = ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    # Bold Name for Winner (even if not value)
    if row['Win?'] == "🏆 WINNER":
        styles[0] = 'font-weight: 900; color: #FF4B4B; text-decoration: underline;' 
    return styles

# --- 3. DATA FETCH ---
@st.cache_data(ttl=60)
def get_data():
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    # Try Standard Cards first
    url = "https://api.theracingapi.com/v1/racecards/standard"
    try:
        r = requests.get(url, auth=auth, timeout=15)
        data = r.json().get('racecards', [])
        # If today's live cards are finished, pull from Results
        if not data:
            r_res = requests.get("https://api.theracingapi.com/v1/results", auth=auth, timeout=15)
            data = r_res.json().get('results', [])
        return data
    except: return []

# --- 4. SIDEBAR ---
st.sidebar.header("⚙️ Strategy Filters")
min_score = st.sidebar.slider("Minimum Horse Score", 0, 50, 0)
only_show_value = st.sidebar.checkbox("Only show 'Value' bets", value=False)

if st.session_state.history:
    st.sidebar.divider()
    df_h = pd.DataFrame(st.session_state.history)
    wins = df_h[df_h['Result'] == 'Win'].shape[0]
    sr = (wins / len(df_h)) * 100 if len(df_h) > 0 else 0
    st.sidebar.metric("Test Week Strike Rate", f"{sr:.1f}%")
    if st.sidebar.button("Clear History"):
        st.session_state.history = []
        st.rerun()

# --- 5. MAIN LOGIC ---
if st.button('🚀 Run Analysis'):
    races = get_data()
    if not races:
        st.warning("No data found for today's cards or results.")
    else:
        st.info(f"Last updated: {datetime.now().strftime('%H:%M:%S')}")
        all_export_data = [] 
        total_v = 0

        for race in races:
            runners = race.get('runners', [])
            race_going = race.get('going', '')
            course = race.get('course', 'Unknown')
            off_time = race.get('off_time', '00:00')

            for r in runners:
                if not r.get('horse'): continue
                
                best_dec = get_best_odds(r)
                score = get_score(r, race_going)
                is_v = score >= 20 and best_dec >= 5.0
                
                # Winner Detection
                pos = str(r.get('position', '')).strip()
                is_winner = "🏆 WINNER" if pos == "1" else ""
                
                display_odds = f"{int(best_dec-1)}/1" if best_dec > 1.0 else "N/A"
                
                if score >= min_score:
                    if only_show_value and not is_v: continue
                    all_export_data.append({
                        "Time": off_time,
                        "Course": course,
                        "Horse": r.get('horse'),
                        "Score": score,
                        "Odds": display_odds,
                        "Value": "💎 YES" if is_v else "",
                        "Win?": is_winner
                    })
                    if is_v: total_v += 1

        # Summary
        c1, c2, c3 = st.columns(3)
        c1.metric("Meetings", len(races))
        c2.metric("Value Bets", total_v)
        c3.metric("API Tier", "Standard ✅")

        # Tables
        for race in races:
            m_rows = [row for row in all_export_data if row['Course'] == race.get('course') and row['Time'] == race.get('off_time')]
            if m_rows:
                with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({race.get('going', 'Unknown')})"):
                    df_display = pd.DataFrame(m_rows)[["Horse", "Score", "Odds", "Value", "Win?"]]
                    st.dataframe(df_display.style.apply(style_rows, axis=1), use_container_width=True, hide_index=True)
                    
                    # Result Logger
                    h_list = [row['Horse'] for row in m_rows]
                    selected_h = st.selectbox("Log Result:", ["- Select -"] + h_list, key=f"log_{race.get('off_time')}_{race.get('course')}")
                    cw, cl = st.columns(2)
                    if selected_h != "- Select -":
                        if cw.button(f"✅ Win", key=f"win_{selected_h}"):
                            st.session_state.history.append({"Horse": selected_h, "Result": "Win"})
                            st.toast(f"Logged Win for {selected_h}!")
                        if cl.button(f"❌ Loss", key=f"loss_{selected_h}"):
                            st.session_state.history.append({"Horse": selected_h, "Result": "Loss"})
                            st.toast(f"Logged Loss for {selected_h}")
