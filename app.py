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
    "Ascot": "Right", "Sandown": "Right", "Chester": "Left", "Epsom": "Left",
    "Doncaster": "Left", "York": "Left", "Goodwood": "Right", "Haydock": "Left"
}

st.set_page_config(page_title="Value Finder Pro V5.6.2", layout="wide")
st.title("🏇 Value Finder Pro: Bankroll Shield")

# --- 2. SIDEBAR ---
st.sidebar.header("🛡️ Strategy Settings")
race_filter = st.sidebar.selectbox("Race Type Filter", ["Handicaps Only", "All Race Types"], index=0)
stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=5, step=1)
min_score = st.sidebar.slider("Min Value Score", 0, 60, 25, 5)

st.sidebar.divider()
st.sidebar.subheader("💎 Value Protection")
min_place_return = st.sidebar.checkbox("🚀 Enable Bankroll Shield", value=True, help="Only shows horses where Place Odds >= 2.0")
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
    # Default columns if sheet fails to load (Now 12 columns)
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Place_Odds", "Stake", "Result", "Pos", "P/L", "Market_Move"])

# --- 4. THE MASTER SCORING ENGINE ---
def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    is_elite = False
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15
            reasons.append("✅ LTO Winner")
        
        curr_class = pd.to_numeric(race_data.get('class'), errors='coerce')
        last_class = pd.to_numeric(r_data.get('last_class'), errors='coerce')
        if curr_class and last_class and curr_class > last_class: 
            s += 10
            reasons.append(f"📉 Class Drop (C{int(last_class)} -> C{int(curr_class)})")

        headgear = str(r_data.get('headgear', '')).lower()
        if '1' in headgear:
            s += 10
            reasons.append(f"🎭 1st Time Headgear ({headgear.upper()})")

        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict):
            win_pc = pd.to_numeric(t_stats.get('percent', 0), errors='coerce') or 0
            runs = pd.to_numeric(t_stats.get('runs', 0), errors='coerce') or 0
            if win_pc >= 20: 
                s += 15
                reasons.append(f"🔥 Trainer Hot ({int(win_pc)}%)")
            elif win_pc == 0 and runs >= 5:
                s -= 10
                reasons.append("❄️ Trainer Cold (0% in 14d)")

        jky = str(r_data.get('jockey', ''))
        is_elite = any(elite in jky for elite in ELITE_JOCKEYS)
        if is_elite:
            s += 10
            reasons.append(f"🏇 Elite Jockey: {jky}")

        cd_flag = str(r_data.get('cd', '')).upper()
        if 'CD' in cd_flag: s += 10; reasons.append("🎯 Course & Distance")
        
        curr_w = pd.to_numeric(r_data.get('weight_lbs'), errors='coerce')
        last_w = pd.to_numeric(r_data.get('last_weight_lbs'), errors='coerce')
        if curr_w and last_w and (last_w - curr_w >= 3):
            s += 5; reasons.append(f"⚖️ Weight Drop (-{int(last_w - curr_w)}lbs)")
    except: pass
    return s, reasons, is_elite

def get_safe_odds(runner):
    try:
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

# --- 5. INTERFACE ---
tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Analyzing markets..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.all_races = data.get('racecards', [])
                st.session_state.value_horses = []
                
                for race in st.session_state.all_races:
                    is_hcap = "Handicap" in str(race.get('race_name', ''))
                    if race_filter == "Handicaps Only" and not is_hcap: continue
                        
                    for r_data in race.get('runners', []):
                        score, reasons, is_elite = get_advanced_score(r_data, race)
                        odds = get_safe_odds(r_data)
                        p_odds = ((odds - 1) / 5) + 1
                        
                        if min_place_return and p_odds < 2.0: continue
                        
                        if score >= min_score and odds >= 5.0:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time', 'N/A'),
                                "Odds": odds, 
                                "Score": score, 
                                "Place_Odds": round(p_odds, 2),
                                "Stake": stake_input,
                                "Analysis": reasons, 
                                "Elite": is_elite
                            })
                st.success("Analysis Complete.")

    if st.session_state.value_horses:
        st.divider()
        st.subheader("🎯 High-Probability Selections")
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        vcols = st.columns(min(len(sorted_val), 4))
        for i, h in enumerate(sorted_val[:4]):
            with vcols[i]:
                is_triple = h['Score'] >= 35 and h['Elite']
                color = "#FFD700" if is_triple else "#f0f2f6"
                st.markdown(f"""<div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; text-align:center;">
                <h2 style='margin:0;'>{h['Horse']}</h2><b>{h['Time']} - {h['Course']}</b><br>Score: {h['Score']} | Win: {h['Odds']} | Place: {h['Place_Odds']}
                {"<br>⭐ <b>TRIPLE SIGNAL</b>" if is_triple else ""}</div>""", unsafe_allow_html=True)
        
        # --- UPDATED LOGGING SECTION (12 COLUMNS) ---
        if st.button("📤 LOG SELECTIONS"):
            ledger = load_ledger()
            log_data = []
            for h in st.session_state.value_horses:
                log_data.append({
                    "Date": h["Date"],
                    "Horse": h["Horse"],
                    "Course": h["Course"],
                    "Time": h["Time"],
                    "Odds": h["Odds"],
                    "Score": h["Score"],
                    "Place_Odds": h["Place_Odds"],
                    "Stake": h["Stake"]
                })
            
            new_df = pd.DataFrame(log_data)
            for col in ["Result", "Pos", "P/L", "Market_Move"]:
                new_df[col] = "Pending" if col == "Result" else 0.0
            
            updated_df = pd.concat([ledger, new_df[~new_df['Horse'].isin(ledger['Horse'])]], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.balloons()

    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        for race in st.session_state.all_races:
            is_hcap = "Handicap" in str(race.get('race_name', ''))
            if race_filter == "Handicaps Only" and not is_hcap: continue
            
            runners = race.get('runners', [])
            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')}"):
                for r in runners:
                    score, reasons, _ = get_advanced_score(r, race)
                    odds = get_safe_odds(r)
                    p_odds = round(((odds - 1) / 5) + 1, 2)
                    st.write(f"**{r.get('horse')}** | Score: {score} | Win: {odds} | Place: {p_odds}")

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_container_width=True)
