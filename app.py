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

# Champion Jockeys for the "Elite Performance" Mode
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

st.set_page_config(page_title="Value Finder Pro V6.8", layout="wide")

# --- 2. THE PRECISION ENGINES ---
def get_race_category(race):
    """Accurately distinguishes between Jumps, AW, and Turf."""
    is_jumps_data = race.get('jumps', '')
    race_type = str(race.get('type', '')).lower()
    surface = str(race.get('surface', '')).upper()
    if is_jumps_data and len(str(is_jumps_data).strip()) > 0:
        return "Jumps"
    if "flat" in race_type:
        return "Flat (AW)" if ("AW" in surface or "STANDARD" in surface) else "Flat (Turf)"
    return "Flat (Turf)"

def get_safe_odds(runner):
    """Safely extracts decimal odds."""
    try:
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

def get_advanced_score(r_data, race_data):
    """Master Scoring Engine - returns score and flags for elite personnel."""
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
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Place_Odds", "Stake", "Result", "Pos", "P/L"])

def show_tracker():
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        df['PL_Num'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        # Dynamic grouping for stats
        def quick_cat(c):
            c = str(c).upper()
            return "Flat (AW)" if "(AW)" in c else ("Jumps" if any(j in c for j in ["KELSO", "AINTREE", "FAIRYHOUSE"]) else "Flat (Turf)")
        df['Internal_Cat'] = df['Course'].apply(quick_cat)
        stats = df.groupby('Internal_Cat')['PL_Num'].sum()
        
        st.subheader("📊 Live Pot-Building Tracker")
        c1, c2, c3 = st.columns(3)
        c1.metric("Flat (AW)", f"£{stats.get('Flat (AW)', 0):.2f}")
        c2.metric("Jumps", f"£{stats.get('Jumps', 0):.2f}")
        c3.metric("Flat (Turf)", f"£{stats.get('Flat (Turf)', 0):.2f}")
        st.divider()

# --- 4. INTERFACE ---
st.title("🏇 Value Finder Pro V6.8")
show_tracker()

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

# Sidebar - MODE SELECTOR
st.sidebar.header("🕹️ Strategy Mode")
app_mode = st.sidebar.radio("Active Engine:", ["Value Strategy", "Elite Performance"])

st.sidebar.divider()
st.sidebar.header("🛡️ Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
min_score = st.sidebar.slider("Min Value Score", 0, 60, 30 if app_mode == "Value Strategy" else 20)
stake_input = st.sidebar.number_input("Base Stake (£)", value=5)

st.sidebar.divider()
st.sidebar.subheader("🔍 Browser Tools")
hide_non_value = st.sidebar.toggle("Hide Non-Selection Races", value=True)

if 'value_horses' not in st.session_state: st.session_state.value_horses = []
if 'all_races' not in st.session_state: st.session_state.all_races = []

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner(f"Analyzing {app_mode} picks..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.value_horses = []
                st.session_state.all_races = data.get('racecards', [])
                
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    if code_filter != "All Codes" and cat != code_filter: continue
                    
                    # Place Logic
                    num_r = len(race.get('runners', []))
                    hcap = "Handicap" in str(race.get('race_name', ''))
                    places = 2 if num_r < 5 else (3 if num_r < 8 else (4 if hcap and num_r >= 16 else 3))

                    for r_data in race.get('runners', []):
                        score, reasons, is_elite, is_hot = get_advanced_score(r_data, race)
                        odds = get_safe_odds(r_data)
                        p_odds = round(((odds - 1) / 4) + 1, 2)
                        
                        # Selection Switch
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
                st.success(f"Analysis Complete. Found {len(st.session_state.value_horses)} picks.")

    # Selection Cards
    if st.session_state.value_horses:
        st.subheader("🎯 Actionable Strategy Cards")
        vcols = st.columns(min(len(st.session_state.value_horses), 4))
        for i, h in enumerate(st.session_state.value_horses[:4]):
            with vcols[i]:
                color = "#FFD700" if "VALUE" in h['Tag'] else "#00FFCC"
                st.markdown(f"""
                <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; min-height:300px;">
                    <h3 style='margin:0;'>{h['Horse']}</h3>
                    <b>{h['Time']} - {h['Course']}</b><br>
                    <small>{h['Category']}</small><hr style='border-color:black;'>
                    <b style='font-size:1.1em;'>{h['Tag']}</b><br>
                    Win: {h['Odds']} | Place: {h['Place_Odds']}<br>
                    <b>Market:</b> Paying {h['Places']} Places<br>
                    <div style="background-color:rgba(255,255,255,0.4); padding:5px; border-radius:5px; margin-top:10px; font-size:0.85em;">
                        <b>ADVICE:</b> Use Bet365 <i>Each Way Extra</i> for {h['Places']+1} places.<br>
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

    # Racecard Browser
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        for race in st.session_state.all_races:
            cat = get_race_category(race)
            if code_filter != "All Codes" and cat != code_filter: continue
            
            # Selection check for "Hide" toggle
            has_sel = any(get_advanced_score(r, race)[0] >= min_score for r in race.get('runners', []))
            if hide_non_value and not has_sel: continue

            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({cat})"):
                for r in race.get('runners', []):
                    s, reasons, is_e, is_h = get_advanced_score(r, race)
                    o = get_safe_odds(r)
                    style = "color: green; font-weight: bold;" if (s >= min_score and o >= 5.0) else "color: gray;"
                    st.markdown(f"<span style='{style}'>{r.get('horse')}</span> | Score: {s} | Odds: {o} | {', '.join(reasons)}", unsafe_allow_html=True)

with tab2:
    st.dataframe(load_ledger(), use_container_width=True)
