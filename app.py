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

ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]
JUMPS_TRACKS = ["AINTREE", "CHELTENHAM", "PUNCHESTOWN", "FAIRYHOUSE", "KELSO", "MUSSELBURGH", "UTTOXETER", "WINCANTON"]

st.set_page_config(page_title="Value Finder Pro V6.2", layout="wide")

# --- 2. HELPERS & CLASSIFICATION ---
def get_race_category(race):
    surface = str(race.get('surface', '')).upper()
    course = str(race.get('course', '')).upper()
    is_jumps = str(race.get('jumps', '')).strip() != ""
    if "AW" in surface or "DUNDALK" in course or "WOLVERHAMPTON" in course:
        return "Flat (AW)"
    elif is_jumps or any(j in course for j in JUMPS_TRACKS):
        return "Jumps"
    return "Flat (Turf)"

def get_safe_odds(runner):
    try:
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

# --- 3. DATABASE & STATS ---
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
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Place_Odds", "Stake", "Result", "Pos", "P/L"])

def show_live_tracker():
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        # Internal classification for stats
        def quick_class(c):
            c = str(c).upper()
            if "AW" in c or "DUNDALK" in c: return "Flat (AW)"
            if any(j in c for j in JUMPS_TRACKS): return "Jumps"
            return "Flat (Turf)"
        
        df['Internal_Type'] = df['Course'].apply(quick_class)
        df['PL_Num'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        stats = df.groupby('Internal_Type')['PL_Num'].sum()
        
        st.subheader("📊 Live Pot-Building Tracker")
        m1, m2, m3 = st.columns(3)
        m1.metric("All-Weather P/L", f"£{stats.get('Flat (AW)', 0):.2f}", delta="Reliability Engine")
        m2.metric("Jumps P/L", f"£{stats.get('Jumps', 0):.2f}", delta="High Value Hunt")
        m3.metric("Turf P/L", f"£{stats.get('Flat (Turf)', 0):.2f}")
        st.divider()

# --- 4. THE MASTER SCORING ENGINE ---
def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15
            reasons.append("✅ LTO Winner")
        
        curr_class = pd.to_numeric(race_data.get('class'), errors='coerce')
        last_class = pd.to_numeric(r_data.get('last_class'), errors='coerce')
        if curr_class and last_class and curr_class > last_class: 
            s += 10
            reasons.append("📉 Class Drop")

        if '1' in str(r_data.get('headgear', '')):
            s += 10
            reasons.append("🎭 1st Headgear")

        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict) and pd.to_numeric(t_stats.get('percent', 0), errors='coerce') >= 20: 
            s += 15
            reasons.append("🔥 Trainer Hot")

        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 10
            reasons.append("🏇 Elite Jockey")

        if 'CD' in str(r_data.get('cd', '')).upper(): 
            s += 10; reasons.append("🎯 C&D")
    except: pass
    return s, reasons

# --- 5. INTERFACE ---
st.title("🏇 Value Finder Pro V6.2")
show_live_tracker()

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

# Sidebar Updates
st.sidebar.header("🛡️ Strategy Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
race_filter = st.sidebar.selectbox("Race Type", ["Handicaps Only", "All Races"], index=0)
min_score = st.sidebar.slider("Min Value Score", 0, 60, 30, 5)
stake_input = st.sidebar.number_input("Base Stake (£)", value=5)

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Processing Master Scoring Engine..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.value_horses = []
                st.session_state.all_races = data.get('racecards', [])
                
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    if code_filter != "All Codes" and cat != code_filter: continue
                    if race_filter == "Handicaps Only" and "Handicap" not in str(race.get('race_name', '')): continue
                        
                    for r_data in race.get('runners', []):
                        score, reasons = get_advanced_score(r_data, race)
                        odds = get_safe_odds(r_data)
                        p_odds = ((odds - 1) / 4) + 1
                        
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
                                "Category": cat
                            })
                st.success("Analysis Complete.")

    if 'value_horses' in st.session_state and st.session_state.value_horses:
        st.subheader("🎯 Strategy-Specific Selections")
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        vcols = st.columns(min(len(sorted_val), 4))
        
        for i, h in enumerate(sorted_val[:4]):
            with vcols[i]:
                # THE PIVOT LOGIC
                tag, color, advice = ("🥈 TOP 2 TARGET", "#E5E4E2", "Low Place Value. Use Exchange Top 2.") if h['Place_Odds'] < 2.0 else ("🏆 80/20 VALUE", "#FFD700", "Good Odds. Use Bet365 Each Way Extra.")
                
                st.markdown(f"""
                <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:1px solid #333; text-align:center; min-height:220px;">
                    <h3 style='margin:0;'>{h['Horse']}</h3>
                    <b>{h['Time']} - {h['Course']}</b><br>
                    <hr style='margin:10px 0;'>
                    <b style='font-size:1.1em;'>{tag}</b><br>
                    Win: {h['Odds']} | Place: {h['Place_Odds']}<br>
                    <small>{advice}</small><br>
                    <small>{' | '.join(h['Analysis'])}</small>
                </div>""", unsafe_allow_html=True)
        
        if st.button("📤 LOG SELECTIONS TO SHEETS"):
            ledger = load_ledger()
            new_rows = pd.DataFrame(st.session_state.value_horses)
            for col in ["Result", "Pos", "P/L", "Market_Move"]: new_rows[col] = "Pending"
            updated_df = pd.concat([ledger, new_rows], ignore_index=True).drop_duplicates(subset=['Horse', 'Date'])
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.balloons()

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_container_width=True)
