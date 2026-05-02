import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & DATA MAPS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

# The "Elite" list for the Triple-Star logic
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

st.set_page_config(page_title="Value Finder Pro V5.8.1", layout="wide")
st.title("🏇 Value Finder Pro: Strategy Base")

# --- 2. SIDEBAR ---
st.sidebar.header("🛡️ Strategy Settings")
race_filter = st.sidebar.selectbox("Race Type Filter", ["Handicaps Only", "All Race Types"], index=0)
stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=5, step=1)
min_score = st.sidebar.slider("Min Value Score", 0, 60, 30, 5)

st.sidebar.divider()
st.sidebar.subheader("💎 View Filters")
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
    # Fallback columns if sheet is empty
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Place_Odds", "Stake", "Result", "Pos", "P/L", "Market_Move"])

# --- 4. THE MASTER SCORING ENGINE ---
def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    is_elite = False
    try:
        # LTO Winner
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15
            reasons.append("✅ LTO Winner")
        
        # Class Drop
        curr_class = pd.to_numeric(race_data.get('class'), errors='coerce')
        last_class = pd.to_numeric(r_data.get('last_class'), errors='coerce')
        if curr_class and last_class and curr_class > last_class: 
            s += 10
            reasons.append(f"📉 Class Drop")

        # Headgear
        headgear = str(r_data.get('headgear', '')).lower()
        if '1' in headgear:
            s += 10
            reasons.append(f"🎭 1st Headgear")

        # Trainer Form
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict):
            win_pc = pd.to_numeric(t_stats.get('percent', 0), errors='coerce') or 0
            if win_pc >= 20: 
                s += 15
                reasons.append(f"🔥 Trainer Hot")

        # Jockey Check
        jky = str(r_data.get('jockey', ''))
        is_elite = any(elite in jky for elite in ELITE_JOCKEYS)
        if is_elite:
            s += 10
            reasons.append(f"🏇 Elite Jockey")

        # Course & Distance
        cd_flag = str(r_data.get('cd', '')).upper()
        if 'CD' in cd_flag: s += 10; reasons.append("🎯 C&D")
    except: pass
    return s, reasons, is_elite

def get_safe_odds(runner):
    try:
        # Check SP first, then live decimal odds
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

# --- 5. INTERFACE ---
tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Processing Racecards..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.all_races = data.get('racecards', [])
                st.session_state.value_horses = []
                
                for race in st.session_state.all_races:
                    # Filter for Handicaps if selected
                    is_hcap = "Handicap" in str(race.get('race_name', ''))
                    if race_filter == "Handicaps Only" and not is_hcap: continue
                        
                    for r_data in race.get('runners', []):
                        score, reasons, is_elite = get_advanced_score(r_data, race)
                        odds = get_safe_odds(r_data)
                        p_odds = ((odds - 1) / 4) + 1 # Calculation for Top 4 (1/4 odds)
                        
                        # The "Threshold" rule: Score 30+ and Odds 5.0+
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
                st.success(f"Analysis Complete. Found {len(st.session_state.value_horses)} qualifiers.")
            else:
                st.error("API Connection Failed. Please check credentials.")

    if st.session_state.value_horses:
        st.divider()
        st.subheader("🎯 Qualified Selections")
        # Sort by highest score first
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        
        # Display in a grid (up to 4 columns)
        vcols = st.columns(min(len(sorted_val), 4))
        for i, h in enumerate(sorted_val[:12]): # Display top 12
            with vcols[i % 4]:
                # Visual Labels
                if h['Place_Odds'] < 2.0:
                    strat_label, strat_color, advice = "🥈 TOP 2 TARGET", "#E5E4E2", "Low T4 Value. Check Top 2."
                else:
                    strat_label, strat_color, advice = "🏆 80/20 VALUE", "#FFD700", "Good T4 odds. Standard 80/20."
                
                is_triple = h['Score'] >= 35 and h['Elite']
                border = "4px solid #000" if is_triple else "1px solid #333"

                st.markdown(f"""
                <div style="background-color:{strat_color}; padding:15px; border-radius:10px; color:#000; border:{border}; text-align:center; min-height:220px; margin-bottom:10px;">
                    <h3 style='margin:0;'>{h['Horse']}</h3>
                    <b>{h['Time']} - {h['Course']}</b><br>
                    <hr style='margin:10px 0;'>
                    <b style='font-size:1.1em;'>{strat_label}</b><br>
                    Win: {h['Odds']} | Place: {h['Place_Odds']}<br>
                    <small style='color:#333;'>{advice}</small><br>
                    <small>{' | '.join(h['Analysis'])}</small>
                </div>""", unsafe_allow_html=True)
        
        if st.button("📤 LOG SELECTIONS TO LEDGER"):
            ledger = load_ledger()
            log_data = []
            for h in st.session_state.value_horses:
                log_data.append({
                    "Date": h["Date"], "Horse": h["Horse"], "Course": h["Course"],
                    "Time": h["Time"], "Odds": h["Odds"], "Score": h["Score"],
                    "Place_Odds": h["Place_Odds"], "Stake": h["Stake"],
                    "Result": "Pending", "Pos": 0, "P/L": 0.0, "Market_Move": 0.0
                })
            
            new_df = pd.DataFrame(log_data)
            # Avoid duplicates
            updated_df = pd.concat([ledger, new_df[~new_df['Horse'].isin(ledger['Horse'])]], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.balloons()

    # --- 6. FULL RACE LIST ---
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Full Race Details")
        for race in st.session_state.all_races:
            is_hcap = "Handicap" in str(race.get('race_name', ''))
            if race_filter == "Handicaps Only" and not is_hcap: continue
            
            # Check if race has any qualifiers to decide if we show it
            valid_in_race = [r for r in race.get('runners', []) if get_advanced_score(r, race)[0] >= min_score and get_safe_odds(r) >= 5.0]
            if hide_low_value and not valid_in_race: continue
            
            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')}"):
                for r in race.get('runners', []):
                    s, reasons, _ = get_advanced_score(r, race)
                    o = get_safe_odds(r)
                    if hide_low_value and (s < min_score or o < 5.0): continue
                    
                    st.write(f"**{r.get('horse')}** | Score: {s} | Odds: {o} | {', '.join(reasons)}")

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_container_width=True)
