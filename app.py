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

if st.session_state.history:
    st.sidebar.divider()
    df_h = pd.DataFrame(st.session_state.history)
    wins = len(df_h[df_h['Result'] == 'Win'])
    st.sidebar.metric("Test Week Wins", f"{wins} / {len(df_h)}")

# --- 3. CORE LOGIC (Calibrated to your JSON) ---
def get_best_odds(runner):
    """Deep Scan for SP and Live Bookie Odds with Error Handling"""
    # 1. Check for Result SP
    sp_val = runner.get('sp_dec')
    if sp_val and sp_val not in ['-', '', 'N/A']:
        try: return float(sp_val)
        except: pass
    
    # 2. Check the 'odds' list from Racecards
    odds_list = runner.get('odds', [])
    if isinstance(odds_list, list) and len(odds_list) > 0:
        prices = []
        for entry in odds_list:
            d_val = entry.get('decimal')
            # Only attempt conversion if data exists and isn't a text placeholder
            if d_val and d_val not in ['-', 'SP', '', 'None']:
                try:
                    prices.append(float(d_val))
                except (ValueError, TypeError):
                    continue 
        if prices: return max(prices)
    
    return 0.0

def get_score(h):
    """Scores based on Form, Trainer (14-day), and RTF"""
    s = 0
    # Form Check
    form = str(h.get('form', ''))
    if form and form.endswith('1'): s += 15
    
    # Trainer Check (Using the 14-day percent found in your JSON)
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            t_win = float(t_stats.get('percent', 0))
            if t_win > 25: s += 20
            elif t_win > 15: s += 10
        except: pass
    
    # RTF Check (Running To Form)
    rtf = str(h.get('trainer_rtf', '0')).replace('%','')
    try:
        if float(rtf) > 50: s += 5
    except: pass
    
    return s

def style_table(row):
    styles = [''] * len(row)
    if row.get('Value') == "💎 YES":
        styles = ['background-color: #FFD700; color: black; font-weight: bold'] * len(row)
    return styles

# --- 4. DATA FETCH ---
@st.cache_data(ttl=60)
def fetch_data():
    if not API_USER or not API_PASS:
        st.error("API Credentials missing!")
        return [], {}
    
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    try:
        # Try Racecards
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth, timeout=15)
        raw_json = r.json()
        data = raw_json.get('racecards', [])
        
        # Fallback to Results
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
        st.warning("No data found. Check back tomorrow morning for live cards.")
    else:
        # Pre-process ALL races to find Top 3 Value Bets
        all_value_horses = []
        for race in races:
            for r in race.get('runners', []):
                odds = get_best_odds(r)
                score = get_score(r)
                prob = int((score / 50) * 100)
                # Value criteria: Score 20+ and Odds 5.0 (4/1) or higher
                if score >= 20 and odds >= 5.0:
                    all_value_horses.append({
                        "Horse": r.get('horse'),
                        "Course": race.get('course'),
                        "Time": race.get('off_time', race.get('off')),
                        "Score": score,
                        "Prob": f"{prob}%",
                        "Odds": f"{int(odds-1)}/1" if odds > 1 else "N/A"
                    })

        # Display Top 3 Summary at the top
        if all_value_horses:
            st.subheader("🌟 Top 3 Daily Value Bets")
            top_3 = sorted(all_value_horses, key=lambda x: x['Score'], reverse=True)[:3]
            cols = st.columns(3)
            for i, horse in enumerate(top_3):
                with cols[i]:
                    st.metric(label=f"{horse['Time']} {horse['Course']}", value=horse['Horse'], delta=f"Odds: {horse['Odds']}")
                    st.caption(f"Prob: {horse['Prob']} | Score: {horse['Score']}/50")
            st.divider()

        # Detailed Meeting Breakdown
        st.subheader("📅 Today's Full Racecards")
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
                
                prob_pct = f"{int((score / 50) * 100)}%"
                is_val = "💎 YES" if (score >= 20 and odds_dec >= 5.0) else ""
                
                if only_show_value and not is_val: continue
                
                race_rows.append({
                    "Horse": r.get('horse'),
                    "Score": score,
                    "Prob %": prob_pct,
                    "Odds": f"{int(odds_dec-1)}/1" if odds_dec > 1.0 else "N/A",
                    "Value": is_val
                })
            
            if race_rows:
                with st.expander(f"🕒 {off_time} - {course}"):
                    df = pd.DataFrame(race_rows)
                    st.dataframe(df.style.apply(style_table, axis=1), use_container_width=True, hide_index=True)

        st.info(f"Last API Sync: {raw_debug.get('last_updated', datetime.now().strftime('%H:%M:%S'))}")
