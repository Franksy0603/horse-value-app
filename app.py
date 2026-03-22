import streamlit as st
import pandas as pd
import requests
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & DATA MAPS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]
COURSE_INFO = {
    "Kempton": "Right", "Wolverhampton": "Left", "Southwell": "Left", 
    "Chelmsford": "Left", "Lingfield": "Left", "Newcastle": "Straight",
    "Ascot": "Right", "Sandown": "Right", "Chester": "Left", "Epsom": "Left"
}

st.set_page_config(page_title="Value Finder Pro V5", layout="wide")
st.title("🏇 Value Finder Pro: Handicap Specialist")

# --- 2. SIDEBAR ---
st.sidebar.header("🛡️ Strategy Settings")
# NEW: Race Type Filter
race_filter = st.sidebar.selectbox(
    "Race Type Filter", 
    ["Handicaps Only", "All Race Types"],
    index=0,
    help="Handicaps are usually best for ROI as form is established."
)

stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=5, step=1)
min_score = st.sidebar.slider("Min Value Score", 0, 50, 25, 5)
hide_low_value = st.sidebar.checkbox("🔍 Hide Non-Value Races", value=True)

if 'value_horses' not in st.session_state: st.session_state.value_horses = []
if 'all_races' not in st.session_state: st.session_state.all_races = []

# --- 3. DATABASE CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Secure API Linked")
except:
    st.sidebar.error("❌ Connection Error")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Market_Move"])

# --- 4. ENGINE FUNCTIONS ---
def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15
            reasons.append("✅ LTO Winner")
        
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict):
            win_pc = pd.to_numeric(t_stats.get('percent', 0), errors='coerce') or 0
            if win_pc >= 20: 
                s += 15
                reasons.append(f"🔥 Trainer Hot ({int(win_pc)}%)")

        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 10
            reasons.append(f"🏇 Elite Jockey: {jky}")

        current_or = pd.to_numeric(r_data.get('or', 0), errors='coerce') or 0
        if 45 <= current_or <= 75:
            s += 5
            reasons.append("⚖️ Prime Handicap Mark")

        if "(AW)" in str(race_data.get('course', '')):
            s += 5
            reasons.append("🌊 AW Specialist")
    except: pass
    return s, reasons

def get_safe_odds(runner):
    try:
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

# --- 5. APP TABS ---
tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Filtering for High-Value Handicaps..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            
            if r.status_code == 200:
                data = r.json()
                st.session_state.all_races = data.get('racecards', [])
                st.session_state.value_horses = []
                
                for race in st.session_state.all_races:
                    # Filter Race Type
                    is_handicap = "Handicap" in str(race.get('race_name', ''))
                    if race_filter == "Handicaps Only" and not is_handicap:
                        continue
                        
                    for r_data in race.get('runners', []):
                        score, reasons = get_advanced_score(r_data, race)
                        odds = get_safe_odds(r_data)
                        if score >= min_score and odds >= 5.0:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time', 'N/A'),
                                "Odds": odds, "Score": score, "Stake": stake_input,
                                "Analysis": reasons
                            })
                st.success(f"Analysis complete.")
            else:
                st.error("API Error.")

    # High-Value "Golden" Cards
    if st.session_state.value_horses:
        st.subheader("🎯 High-Confidence Handicap Selections")
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        cols = st.columns(min(len(sorted_val), 4))
        for i, h in enumerate(sorted_val[:4]):
            with cols[i]:
                color = "#FFD700" if h['Score'] >= 35 else "#f0f2f6"
                st.markdown(f"""<div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; text-align:center;">
                <h3 style='margin:0;'>{h['Horse']}</h3><b>{h['Time']} - {h['Course']}</b><br>Score: {h['Score']} | Odds: {h['Odds']}</div>""", unsafe_allow_html=True)

    # Detailed Race Analysis (WITH DOUBLE FILTER)
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        filtered_count = 0
        
        for race in st.session_state.all_races:
            # 1. Check Race Type Filter
            is_handicap = "Handicap" in str(race.get('race_name', ''))
            if race_filter == "Handicaps Only" and not is_handicap:
                continue
            
            # 2. Check if Race has Value Horses
            runners = race.get('runners', [])
            value_in_race = [r for r in runners if (get_advanced_score(r, race)[0] >= min_score and get_safe_odds(r) >= 5.0)]
            
            if hide_low_value and not value_in_race:
                continue
            
            filtered_count += 1
            direction = next((v for k, v in COURSE_INFO.items() if k in str(race.get('course'))), "Straight")
            
            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({direction})"):
                st.caption(f"Race Type: {race.get('race_name')}")
                for r in runners:
                    score, reasons = get_advanced_score(r, race)
                    odds = get_safe_odds(r)
                    is_val = (score >= min_score and odds >= 5.0)
                    
                    if hide_low_value and not is_val: continue
                    
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 3])
                    c1.write(f"**{r.get('horse')}**")
                    c2.write(f"Score: {score}")
                    c3.write(f"Odds: {odds}")
                    if is_val: c4.write("💎 **VALUE** | " + " | ".join(reasons))
                    elif reasons: c4.caption(" | ".join(reasons))
        
        if filtered_count == 0:
            st.info("No races match your current Handicap and Score filters.")

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_container_width=True)
