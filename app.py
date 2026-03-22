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

# Elite Jockey List
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

# Track Directional Mapping
COURSE_INFO = {
    "Kempton": "Right", "Wolverhampton": "Left", "Southwell": "Left", 
    "Chelmsford": "Left", "Lingfield": "Left", "Newcastle": "Straight",
    "Ascot": "Right", "Sandown": "Right", "Chester": "Left", "Epsom": "Left",
    "Doncaster": "Left", "York": "Left", "Goodwood": "Right", "Haydock": "Left"
}

st.set_page_config(page_title="Value Finder Master V5.1", layout="wide")
st.title("🏇 Value Finder Pro: Master Selection Engine")

# --- 2. SIDEBAR CONTROLS ---
st.sidebar.header("🛡️ Strategy Settings")
race_filter = st.sidebar.selectbox(
    "Race Type Filter", 
    ["Handicaps Only", "All Race Types"],
    index=0,
    help="Handicaps are the most reliable for 'Value' math."
)

stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=5, step=1)
min_score = st.sidebar.slider("Min Value Score", 0, 50, 25, 5)
hide_low_value = st.sidebar.checkbox("🔍 Hide Non-Value Races", value=True)

if 'value_horses' not in st.session_state: st.session_state.value_horses = []
if 'all_races' not in st.session_state: st.session_state.all_races = []

# --- 3. DATABASE CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except:
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Market_Move"])

# --- 4. THE PROFESSIONAL GRADING ENGINE ---
def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    try:
        # A. Win Form
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15
            reasons.append("✅ LTO Winner")
        
        # B. Distance/Course Specialist (CD/D)
        cd_flag = str(r_data.get('cd', '')).upper()
        if 'CD' in cd_flag:
            s += 10
            reasons.append("🎯 Course & Distance Specialist")
        elif 'D' in cd_flag:
            s += 5
            reasons.append("📏 Distance Proven")

        # C. Trainer Performance
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict):
            win_pc = pd.to_numeric(t_stats.get('percent', 0), errors='coerce') or 0
            if win_pc >= 20: 
                s += 15
                reasons.append(f"🔥 Hot Trainer ({int(win_pc)}%)")

        # D. Elite Jockey Booking
        jky = str(r_data.get('jockey', ''))
        is_elite = any(elite in jky for elite in ELITE_JOCKEYS)
        if is_elite:
            s += 10
            reasons.append(f"🏇 Elite Jockey: {jky}")

        # E. Handicap Advantage (OR and Weight)
        current_or = pd.to_numeric(r_data.get('or', 0), errors='coerce') or 0
        if 45 <= current_or <= 75:
            s += 5
            reasons.append("⚖️ Prime Handicap Mark")

        # Weight Drop (-3lbs or more)
        curr_w = pd.to_numeric(r_data.get('weight_lbs'), errors='coerce')
        last_w = pd.to_numeric(r_data.get('last_weight_lbs'), errors='coerce')
        if curr_w and last_w and (last_w - curr_w >= 3):
            s += 5
            reasons.append(f"📉 Weight Drop (-{int(last_w - curr_w)}lbs)")

        # F. All-Weather Specialist
        if "(AW)" in str(race_data.get('course', '')):
            s += 5
            reasons.append("🌊 AW Surface specialist")
            
    except: pass
    return s, reasons, is_elite

def get_safe_odds(runner):
    try:
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

# --- 5. MAIN INTERFACE ---
tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Processing Professional Grade Data..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.all_races = data.get('racecards', [])
                st.session_state.value_horses = []
                
                for race in st.session_state.all_races:
                    # Filter Race Type
                    is_handicap = "Handicap" in str(race.get('race_name', ''))
                    if race_filter == "Handicaps Only" and not is_handicap: continue
                        
                    for r_data in race.get('runners', []):
                        score, reasons, is_elite = get_advanced_score(r_data, race)
                        odds = get_safe_odds(r_data)
                        if score >= min_score and odds >= 5.0:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time', 'N/A'),
                                "Odds": odds, "Score": score, "Stake": stake_input,
                                "Analysis": reasons, "Elite": is_elite
                            })

    # Golden Selections Display
    if st.session_state.value_horses:
        st.subheader("🎯 Professional Selections")
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        vcols = st.columns(min(len(sorted_val), 4))
        for i, h in enumerate(sorted_val[:4]):
            with vcols[i]:
                # TRIPLE SIGNAL: Score 30+ AND Elite Jockey
                is_triple = h['Score'] >= 30 and h['Elite']
                color = "#FFD700" if is_triple else "#f0f2f6"
                st.markdown(f"""<div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; text-align:center;">
                <h2 style='margin:0;'>{h['Horse']}</h2><b>{h['Time']} - {h['Course']}</b><br>Score: {h['Score']} | Odds: {h['Odds']}
                {"<br>⭐ <b>TRIPLE SIGNAL</b>" if is_triple else ""}</div>""", unsafe_allow_html=True)

        if st.button("📤 LOG TO SHEETS"):
            ledger = load_ledger()
            log_data = [{k: v for k, v in h.items() if k != 'Analysis' and k != 'Elite'} for h in st.session_state.value_horses]
            new_df = pd.DataFrame(log_data)
            for col in ["Result", "Pos", "P/L", "Market_Move"]: new_df[col] = "Pending" if col == "Result" else 0.0
            updated_df = pd.concat([ledger, new_df[~new_df['Horse'].isin(ledger['Horse'])]], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.balloons()

    # Detailed Race Analysis
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        f_count = 0
        for race in st.session_state.all_races:
            is_handicap = "Handicap" in str(race.get('race_name', ''))
            if race_filter == "Handicaps Only" and not is_handicap: continue
            
            runners = race.get('runners', [])
            val_runners = [r for r in runners if (get_advanced_score(r, race)[0] >= min_score and get_safe_odds(r) >= 5.0)]
            if hide_low_value and not val_runners: continue
            
            f_count += 1
            direction = next((v for k, v in COURSE_INFO.items() if k in str(race.get('course'))), "Straight")
            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({direction})"):
                st.caption(f"Type: {race.get('race_name')}")
                for r in runners:
                    score, reasons, is_elite = get_advanced_score(r, race)
                    odds = get_safe_odds(r)
                    is_val = (score >= min_score and odds >= 5.0)
                    if hide_low_value and not is_val: continue
                    
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 3])
                    c1.write(f"**{r.get('horse')}**")
                    c2.write(f"Score: {score}")
                    c3.write(f"Odds: {odds}")
                    if is_val: c4.write("💎 **VALUE** | " + " | ".join(reasons))
                    elif reasons: c4.caption(" | ".join(reasons))
        if f_count == 0: st.info("No races match your current filters.")

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_container_width=True)
