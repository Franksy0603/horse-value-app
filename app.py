import streamlit as st
import pandas as pd
import requests
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & DATA MAPS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

# Personnel for Elite Performance Mode
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

st.set_page_config(page_title="Value Finder Pro V6.9", layout="wide")

# --- 2. THE PRECISION ENGINES ---
def get_race_category(race):
    """Accurately identifies race code based on API data tags."""
    is_jumps_data = race.get('jumps', '')
    race_type = str(race.get('type', '')).lower()
    surface = str(race.get('surface', '')).upper()
    if is_jumps_data and len(str(is_jumps_data).strip()) > 0:
        return "Jumps"
    if "flat" in race_type:
        return "Flat (AW)" if ("AW" in surface or "STANDARD" in surface) else "Flat (Turf)"
    return "Flat (Turf)"

def get_safe_odds(runner):
    """Safely extracts decimal odds from API."""
    try:
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

def get_advanced_score(r_data, race_data):
    """Scoring Engine - returns total score and personnel flags."""
    s = 0
    reasons = []
    is_elite_jky = False
    is_hot_trn = False
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15; reasons.append("✅ LTO Winner")
        if 'CD' in str(r_data.get('cd', '')).upper(): 
            s += 10; reasons.append("🎯 C&D")
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict) and pd.to_numeric(t_stats.get('percent', 0), errors='coerce') >= 20: 
            s += 15; reasons.append("🔥 Trainer Hot")
            is_hot_trn = True
        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 10; reasons.append("🏇 Elite Jockey")
            is_elite_jky = True
        if '1' in str(r_data.get('headgear', '')):
            s += 10; reasons.append("🎭 1st Headgear")
    except: pass
    return s, reasons, is_elite_jky, is_hot_trn

# --- 3. DATABASE & ANALYTICS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except:
    conn = None

def load_ledger():
    """Reads the current performance from Google Sheets."""
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Place_Odds", "Stake", "Result", "Pos", "P/L"])

# --- 4. INTERFACE ---
st.title("🏇 Value Finder Pro V6.9")

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

# Sidebar - MODE SELECTOR
st.sidebar.header("🕹️ Strategy Mode")
app_mode = st.sidebar.radio("Active Engine:", ["Value Strategy", "Elite Performance"])

st.sidebar.divider()
st.sidebar.header("🛡️ Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
min_score = st.sidebar.slider("Min Selection Score", 0, 60, 30 if app_mode == "Value Strategy" else 20)
stake_input = st.sidebar.number_input("Base Stake (£)", value=5)

st.sidebar.divider()
st.sidebar.subheader("🔍 Browser Settings")
hide_non_selection = st.sidebar.toggle("Hide Races Without Picks", value=True)

# Session State Initialization
if 'value_horses' not in st.session_state: st.session_state.value_horses = []
if 'all_races' not in st.session_state: st.session_state.all_races = []

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner(f"Scanning market for {app_mode}..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.value_horses = []
                st.session_state.all_races = data.get('racecards', [])
                
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    if code_filter != "All Codes" and cat != code_filter: continue
                    
                    num_r = len(race.get('runners', []))
                    hcap = "Handicap" in str(race.get('race_name', ''))
                    places = 2 if num_r < 5 else (3 if num_r < 8 else (4 if hcap and num_r >= 16 else 3))

                    for r_data in race.get('runners', []):
                        score, reasons, is_elite, is_hot = get_advanced_score(r_data, race)
                        odds = get_safe_odds(r_data)
                        p_odds = round(((odds - 1) / 4) + 1, 2)
                        
                        # Logic switch for the two modes
                        if app_mode == "Value Strategy":
                            match = (score >= min_score and odds >= 5.0)
                            tag = "🏆 VALUE PLAY"
                        else:
                            match = (odds < 5.0 and (is_elite or is_hot))
                            tag = "⚡ ELITE BANKER"

                        if match:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time', 'N/A'),
                                "Odds": odds, "Score": score, "Place_Odds": p_odds,
                                "Places": places, "Tag": tag, "Analysis": reasons, "Category": cat, "Stake": stake_input
                            })
                st.success(f"Analysis Complete! Found {len(st.session_state.value_horses)} selections.")

    # 🎯 DISPLAY ACTION CARDS
    if st.session_state.value_horses:
        st.subheader("🎯 Actionable Strategy Cards")
        sorted_h = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        vcols = st.columns(min(len(sorted_h), 4))
        for i, h in enumerate(sorted_h[:4]):
            with vcols[i]:
                color = "#FFD700" if "VALUE" in h['Tag'] else "#00FFCC"
                st.markdown(f"""
                <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; min-height:280px;">
                    <h3 style='margin:0;'>{h['Horse']}</h3>
                    <b>{h['Time']} - {h['Course']}</b><br><small>{h['Category']}</small>
                    <hr style='border-color:black;'>
                    <b>{h['Tag']}</b><br>
                    Win: {h['Odds']} | Place: {h['Place_Odds']}<br>
                    <b>Paying {h['Places']} Places</b><br>
                    <div style="background-color:rgba(255,255,255,0.4); padding:5px; border-radius:5px; margin-top:10px; font-size:0.8em;">
                        <b>ADVICE:</b> Use Bet365 Each Way Extra for {h['Places']+1} places.<br>
                        {' | '.join(h['Analysis'])}
                    </div>
                </div>""", unsafe_allow_html=True)
        
        if st.button("📤 LOG SELECTIONS TO SHEETS"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            for col in ["Result", "Pos", "P/L"]: new_df[col] = "Pending"
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.balloons()

    # 🏁 THE SYNCED BROWSER
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        for race in st.session_state.all_races:
            cat = get_race_category(race)
            if code_filter != "All Codes" and cat != code_filter: continue
            
            # Logic: Show race if it contains ANY of our found horses
            horse_names_in_this_race = [r.get('horse') for r in race.get('runners', [])]
            sel_in_race = [h for h in st.session_state.value_horses if h['Horse'] in horse_names_in_this_race and h['Time'] == race.get('off_time')]
            
            if hide_non_selection and not sel_in_race: continue

            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({cat})"):
                for r in race.get('runners', []):
                    s, reasons, is_e, is_h = get_advanced_score(r, race)
                    o = get_safe_odds(r)
                    
                    # Highlight if this runner is one of our session picks
                    is_pick = any(p['Horse'] == r.get('horse') and p['Time'] == race.get('off_time') for p in st.session_state.value_horses)
                    style = "color: #008000; font-weight: bold; font-size: 1.1em;" if is_pick else "color: gray;"
                    
                    st.markdown(f"<span style='{style}'>{r.get('horse')}</span> | Score: {s} | Odds: {o} | {', '.join(reasons)}", unsafe_allow_html=True)

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_container_width=True)
