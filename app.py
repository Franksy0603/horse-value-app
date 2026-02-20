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
    """Aggressively hunts for any price: Live, SP, or Fallbacks"""
    # 1. Check Starting Price first (for finished races)
    sp = runner.get('sp') or runner.get('starting_price')
    if sp and isinstance(sp, str) and '/' in sp:
        return odds_to_dec(sp)

    # 2. Check the dictionary of multiple bookies
    bookies = runner.get('bookmaker_odds', {})
    if isinstance(bookies, dict) and bookies:
        decimal_prices = []
        for val in bookies.values():
            if isinstance(val, str) and '/' in val:
                dec = odds_to_dec(val)
                if dec > 1.0: decimal_prices.append(dec)
        if decimal_prices:
            return max(decimal_prices)

    # 3. Last resort fallback fields
    fallback = runner.get('odds') or runner.get('best_odds')
    if fallback and isinstance(fallback, str) and '/' in fallback:
        return odds_to_dec(fallback)
        
    return 0.0

def get_score(h, race_going):
    """Scores based on Form and Trainer Stats"""
    s = 0
    # Form Check
    form = str(h.get('form', h.get('last_run_result', '')))
    if form and form[-1] == '1': s += 15
    
    # Trainer Check (handles nested stats dict or flat fields)
    t_stats = h.get('trainer_stats', {})
    t_win = 0
    if isinstance(t_stats, dict):
        t_win = t_stats.get('win_percentage', 0)
    else:
        t_win = h.get('trainer_win_percentage', 0)
        
    if t_win > 25: s += 20
    elif t_win > 15: s += 10
    
    # Ground Check
    horse_best = str(h.get('best_going', h.get('going_preference', ''))).lower()
    if race_going and str(race_going).lower() in horse_best:
        s += 10 
    return s

def highlight_value(row):
    """Applies Gold highlighting for Value bets"""
    if row['Value'] == "💎 YES":
        return ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    return [''] * len(row)

# --- 3. DUAL-FETCH DATA SYSTEM ---
@st.cache_data(ttl=60)
def get_combined_data():
    """Tries Standard Cards, then falls back to Results for finished races"""
    headers = {"Accept": "application/json"}
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    
    # Try Standard Cards
    url_cards = "https://api.theracingapi.com/v1/racecards/standard"
    try:
        r = requests.get(url_cards, auth=auth, timeout=15)
        cards = r.json().get('racecards', [])
        
        # If evening/late, try the Results endpoint for today's data
        if not cards:
            url_res = "https://api.theracingapi.com/v1/results"
            r_res = requests.get(url_res, auth=auth, timeout=15)
            cards = r_res.json().get('results', [])
            
        return cards
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return []

# --- 4. SIDEBAR ---
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
    races = get_combined_data()
    
    if not races:
        st.warning("No data found for today's cards or results.")
    else:
        st.info(f"Last updated at: {datetime.now().strftime('%H:%M:%S')}")
        all_export_data = [] 
        total_v = 0

        for race in races:
            runners = race.get('runners', [])
            course_name = race.get('course', 'Unknown')
            off_time = race.get('off_time', '00:00')
            race_going = race.get('going', '')

            # --- CRASH-PROOF INSPECTOR ---
            if st.checkbox(f"🔍 Inspect Raw Data: {off_time} - {course_name}", key=f"inspect_{off_time}_{course_name}"):
                if runners and len(runners) > 0:
                    st.write(f"Showing raw data for the first horse at {course_name}:")
                    st.json(runners[0])
                else:
                    st.warning("No runner data available in this race object.")

            for r in runners:
                best_dec = get_best_odds(r)
                score = get_score(r, race_going)
                is_v = score >= 20 and best_dec >= 5.0
                display_odds = f"{int(best_dec-1)}/1" if best_dec > 1.0 else "N/A"
                
                if score >= min_score:
                    if only_show_value and not is_v: continue
                    all_export_data.append({
                        "Time": off_time,
                        "Course": course_name,
                        "Horse": r.get('horse'),
                        "Score": score,
                        "Odds": display_odds,
                        "Value": "💎 YES" if is_v else ""
                    })
                    if is_v: total_v += 1

        # DASHBOARD
        c1, c2, c3 = st.columns(3)
        c1.metric("Meetings Found", len(races))
        c2.metric("Value Bets", total_v)
        c3.metric("API Status", "Connected ✅")

        # DISPLAY TABLES
        for race in races:
            m_rows = [row for row in all_export_data if row['Course'] == race.get('course') and row['Time'] == race.get('off_time')]
            if m_rows:
                with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({race.get('going', 'Unknown')})"):
                    df_display = pd.DataFrame(m_rows)[["Horse", "Score", "Odds", "Value"]]
                    st.dataframe(df_display.style.apply(highlight_value, axis=1), use_container_width=True, hide_index=True)
                    
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
