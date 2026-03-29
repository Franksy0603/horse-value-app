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

st.set_page_config(page_title="Value Finder Pro V5.6", layout="wide")
st.title("🏇 Value Finder Pro: Bankroll Shield Edition")

# --- 2. SIDEBAR ---
st.sidebar.header("🛡️ Strategy Settings")
race_filter = st.sidebar.selectbox("Race Type Filter", ["Handicaps Only", "All Race Types"], index=0)
stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=5, step=1)
min_score = st.sidebar.slider("Min Value Score", 0, 60, 25, 5)

st.sidebar.divider()
st.sidebar.subheader("💎 Value Protection")
# NEW: The Bankroll Shield Toggle
min_place_return = st.sidebar.checkbox("🚀 Enable Bankroll Shield", value=True, help="Only shows horses with a Place Return of 2.0 or higher.")
hide_low_value = st.sidebar.checkbox("🔍 Hide Non-Value Races", value=True)

st.sidebar.divider()
st.sidebar.subheader("🧮 Place Value Calculator")
calc_win_odds = st.sidebar.number_input("Current Win Odds", value=10.0)
est_place = ((calc_win_odds - 1) / 5) + 1
st.sidebar.caption(f"Standard Bookie Place Odds: {est_place:.2f}")
if est_place < 2.0:
    st.sidebar.error("⚠️ Poor Value: Risk > Reward")
else:
    st.sidebar.success("✅ Profitable Place Potential")

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
        with st.spinner("Compiling Shrewd Selections..."):
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
                        
                        # Apply Bankroll Shield Filter
                        if min_place_return and p_odds < 2.0: continue
                        
                        if score >= min_score and odds >= 5.0:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time', 'N/A'),
                                "Odds": odds, 
                                "Place_Odds": round(p_odds, 2),
                                "Score": score, 
                                "Stake": stake_input,
                                "Analysis": reasons, 
                                "Elite": is_elite
                            })
                st.success("Analysis Complete.")

    if st.session_state.value_horses:
        st.divider()
        m1, m2, m3 = st.columns(3)
        total_found = len(st.session_state.value_horses)
        triples = len([h for h in st.session_state.value_horses if h['Score'] >= 35 and h['Elite']])
        m1.metric("Selections Found", total_found)
        m2.metric("High-Value Plays", triples)
        m3.metric("Avg. Place ROI", f"{round(sum(h['Place_Odds'] for h in st.session_state.value_horses)/total_found, 2)}x")

        st.subheader("🎯 Filtered Strategy Selections")
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        vcols = st.columns(min(len(sorted_val), 4))
        for i, h in enumerate(sorted_val[:4]):
            with vcols[i]:
                is_triple = h['Score'] >= 35 and h['Elite']
                color = "#FFD700" if is_triple else "#f0f2f6"
                st.markdown(f"""<div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; text-align:center;">
                <h2 style='margin:0;'>{h['Horse']}</h2><b>{h['Time']} - {h['Course']}</b><br>Score: {h['Score']} | Win: {h['Odds']} | Place: {h['Place_Odds']}
                {"<br>⭐ <b>TRIPLE SIGNAL</b>" if is_triple else ""}</div>""", unsafe_allow_html=True)
        
        if st.button("📤 LOG SELECTIONS"):
            ledger = load_ledger()
            log_data = [{k: v for k, v in h.items() if k not in ['Analysis', 'Elite', 'Place_Odds']} for h in st.session_state.value_horses]
            new_df = pd.DataFrame(log_data)
            for col in ["Result", "Pos", "P/L", "Market_Move"]: new_df[col] = "Pending" if col == "Result" else 0.0
            updated_df = pd.concat([ledger, new_df[~new_df['Horse'].isin(ledger['Horse'])]], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.balloons()

    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        f_count = 0
        for race in st.session_state.all_races:
            is_hcap = "Handicap" in str(race.get('race_name', ''))
            if race_filter == "Handicaps Only" and not is_hcap: continue
            
            runners = race.get('runners', [])
            val_runners = []
            for r in runners:
                s, _, _ = get_advanced_score(r, race)
                o = get_safe_odds(r)
                p = ((o - 1) / 5) + 1
                if s >= min_score and o >= 5.0 and (not min_place_return or p >= 2.0):
                    val_runners.append(r)
            
            if hide_low_value and not val_runners: continue
            
            f_count += 1
            direction = next((v for k, v in COURSE_INFO.items() if k in str(race.get('course'))), "Straight")
            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({direction})"):
                for r in runners:
                    score, reasons, is_elite = get_advanced_score(r, race)
                    odds = get_safe_odds(r)
                    p_odds = round(((odds - 1) / 5) + 1, 2)
                    is_val = (score >= min_score and odds >= 5.0 and (not min_place_return or p_odds >= 2.0))
                    if hide_low_value and not is_val: continue
                    
                    c1, c2, c3, c4 = st.columns([2, 1, 1, 3])
                    c1.write(f"**{r.get('horse')}**")
                    c2.write(f"Score: {score}")
                    c3.write(f"Win: {odds} | Pl: {p_odds}")
                    if is_val: c4.write("💎 **PRO VALUE** | " + " | ".join(reasons))
                    elif reasons: c4.caption(" | ".join(reasons))
        if f_count == 0: st.info("No races match filters.")

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_column_width=True)
