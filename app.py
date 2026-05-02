import streamlit as st
import pandas as pd
import requests
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & CONFIGURATION ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

# Constants for the Master Scoring Engine
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

st.set_page_config(page_title="Value Finder Pro V6.7", layout="wide")

# --- 2. THE PRECISION CATEGORY ENGINE ---
def get_race_category(race):
    """Accurately identifies race code based on API data tags."""
    is_jumps_data = race.get('jumps', '')
    race_type = str(race.get('type', '')).lower()
    surface = str(race.get('surface', '')).upper()
    
    # 1. If 'jumps' tag is populated, it's definitely a National Hunt race
    if is_jumps_data and len(str(is_jumps_data).strip()) > 0:
        return "Jumps"
    
    # 2. Distinguish between All-Weather and Turf for Flat races
    if "flat" in race_type:
        if "AW" in surface or "STANDARD" in surface:
            return "Flat (AW)"
        else:
            return "Flat (Turf)"
            
    return "Flat (Turf)" # Default fallback

def get_safe_odds(runner):
    """Safely extracts decimal odds from the API response."""
    try:
        val = runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal'))
        num = pd.to_numeric(val, errors='coerce')
        return float(num) if num and num > 0 else 1.0
    except: return 1.0

# --- 3. DATABASE & ANALYTICS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except:
    conn = None

def load_ledger():
    """Reads the current performance from your Google Sheet."""
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Place_Odds", "Stake", "Result", "Pos", "P/L"])

def show_advanced_analytics():
    """Calculates ROI and Strike Rate for the top-level tracker."""
    df = load_ledger()
    if not df.empty and 'P/L' in df.columns:
        # Standardize P/L and Stake for calculations
        df['PL_Num'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake_Num'] = pd.to_numeric(df['Stake'], errors='coerce').fillna(5)
        
        # Simple classifier for ledger items based on course naming conventions
        def ledger_class(row):
            c = str(row.get('Course', '')).upper()
            if "(AW)" in c: return "Flat (AW)"
            # Broad check for Jumps; this updates as you log more races
            if any(j in c for j in ["CHELTENHAM", "AINTREE", "FAIRYHOUSE", "PUNCHESTOWN", "KELSO"]): return "Jumps"
            return "Flat (Turf)"
            
        df['Type_Summary'] = df.apply(ledger_class, axis=1)
        stats = df.groupby('Type_Summary').agg(
            Total_PL=('PL_Num', 'sum'),
            Total_Stake=('Stake_Num', 'sum'),
            Count=('Horse', 'count')
        )
        
        st.subheader("📊 Live Pot-Building Tracker")
        c1, c2, c3 = st.columns(3)
        metrics = [("Flat (AW)", c1), ("Jumps", c2), ("Flat (Turf)", c3)]
        
        for name, col in metrics:
            if name in stats.index:
                row = stats.loc[name]
                roi = (row['Total_PL'] / row['Total_Stake'] * 100) if row['Total_Stake'] > 0 else 0
                col.metric(name, f"£{row['Total_PL']:.2f}", f"{roi:.1f}% ROI")
                col.caption(f"🏇 Total Runs: {int(row['Count'])}")
        st.divider()

# --- 4. THE MASTER SCORING ENGINE ---
def get_advanced_score(r_data, race_data):
    """Your core selection logic (Form, Trainer, Jockey, etc)."""
    s = 0
    reasons = []
    try:
        # LTO Winner Check
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15; reasons.append("✅ LTO Winner")
        # Class Drop Check
        curr_class = pd.to_numeric(race_data.get('class'), errors='coerce')
        last_class = pd.to_numeric(r_data.get('last_class'), errors='coerce')
        if curr_class and last_class and curr_class > last_class: 
            s += 10; reasons.append("📉 Class Drop")
        # First-time Headgear
        if '1' in str(r_data.get('headgear', '')):
            s += 10; reasons.append("🎭 1st Headgear")
        # Hot Trainer Check
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict) and pd.to_numeric(t_stats.get('percent', 0), errors='coerce') >= 20: 
            s += 15; reasons.append("🔥 Trainer Hot")
        # Elite Jockey Check
        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 10; reasons.append("🏇 Elite Jockey")
        # Course and Distance Check
        if 'CD' in str(r_data.get('cd', '')).upper(): 
            s += 10; reasons.append("🎯 C&D")
    except: pass
    return s, reasons

# --- 5. INTERFACE & CORE LOGIC ---
st.title("🏇 Value Finder Pro V6.7")
show_advanced_analytics()

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

# Sidebar
st.sidebar.header("🛡️ Strategy Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
min_score = st.sidebar.slider("Min Value Score", 0, 60, 30, 5)
stake_input = st.sidebar.number_input("Base Stake (£)", value=5)

st.sidebar.divider()
st.sidebar.subheader("🔍 Browser Tools")
enable_full_search = st.sidebar.toggle("Search All Racecards", value=False)
hide_non_value = st.sidebar.toggle("Hide Non-Value Races", value=True)

if 'value_horses' not in st.session_state: st.session_state.value_horses = []
if 'all_races' not in st.session_state: st.session_state.all_races = []

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Decoding API & Processing Strategy..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.value_horses = []
                st.session_state.all_races = data.get('racecards', [])
                
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    if code_filter != "All Codes" and cat != code_filter: continue
                    
                    # Calculate Paying Places
                    num_r = len(race.get('runners', []))
                    hcap = "Handicap" in str(race.get('race_name', ''))
                    places = 2 if num_r < 5 else (3 if num_r < 8 else (4 if hcap and num_r >= 16 else 3))

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
                                "Odds": odds, "Score": score, "Place_Odds": round(p_odds, 2),
                                "Places": places, "Category": cat, "Stake": stake_input, "Analysis": reasons
                            })
                st.success("Analysis Complete.")

    # Display Strategy Cards
    if st.session_state.value_horses:
        st.subheader("🎯 Actionable Value Strategy Cards")
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        vcols = st.columns(min(len(sorted_val), 4))
        
        for i, h in enumerate(sorted_val[:4]):
            with vcols[i]:
                # Dynamic Logic for Gold vs Silver
                is_gold = h['Place_Odds'] >= 2.0
                tag, color = ("🏆 80/20 GOLD", "#FFD700") if is_gold else ("🥈 TOP 2 PIVOT", "#E5E4E2")
                
                st.markdown(f"""
                <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; min-height:300px;">
                    <h3 style='margin:0;'>{h['Horse']}</h3>
                    <b>{h['Time']} - {h['Course']}</b><br>
                    <small><i>Category: {h['Category']}</i></small>
                    <hr style='margin:10px 0; border-color:black;'>
                    <b style='font-size:1.1em;'>{tag}</b><br>
                    Win: {h['Odds']} | Place: {h['Place_Odds']}<br>
                    <b>Market:</b> Paying {h['Places']} Places<br>
                    <div style="background-color:rgba(255,255,255,0.4); padding:5px; border-radius:5px; margin-top:10px; font-size:0.85em;">
                        <b>ADVICE:</b> Use Bet365 <i>Each Way Extra</i> to boost to {h['Places']+1} places for security.<br>
                        {' | '.join(h['Analysis'])}
                    </div>
                </div>""", unsafe_allow_html=True)
        
        if st.button("📤 LOG ALL TO GOOGLE SHEETS"):
            ledger = load_ledger()
            new_rows = pd.DataFrame(st.session_state.value_horses)
            for col in ["Result", "Pos", "P/L", "Market_Move"]: new_rows[col] = "Pending"
            updated_df = pd.concat([ledger, new_rows], ignore_index=True).drop_duplicates(subset=['Horse', 'Date'])
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.balloons()

    # Browser Section
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        for race in st.session_state.all_races:
            cat = get_race_category(race)
            if code_filter != "All Codes" and cat != code_filter: continue
            
            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({cat})"):
                for r in race.get('runners', []):
                    s, reasons = get_advanced_score(r, race)
                    o = get_safe_odds(r)
                    is_val = s >= min_score and o >= 5.0
                    style = "color: green; font-weight: bold;" if is_val else "color: gray;"
                    st.markdown(f"<span style='{style}'>{r.get('horse')}</span> | Score: {s} | Odds: {o} | {', '.join(reasons)}", unsafe_allow_html=True)

with tab2:
    st.subheader("Performance Ledger")
    st.dataframe(load_ledger(), use_container_width=True)
