import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & CONFIG ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

st.set_page_config(page_title="Value Finder Pro V7.8", layout="wide")

# --- 2. ENGINES ---
def get_race_category(race):
    is_jumps = race.get('jumps', '')
    race_type = str(race.get('type', '')).lower()
    surface = str(race.get('surface', '')).upper()
    if is_jumps and len(str(is_jumps).strip()) > 0: return "Jumps"
    if "flat" in race_type:
        return "Flat (AW)" if ("AW" in surface or "STANDARD" in surface) else "Flat (Turf)"
    return "Flat (Turf)"

def get_advanced_score(r_data):
    s = 0
    reasons = []
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15; reasons.append("✅ LTO Winner")
        if 'C' in str(r_data.get('cd', '')).upper(): 
            s += 10; reasons.append("🎯 Course Form")
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict):
            pct = pd.to_numeric(t_stats.get('percent', 0), errors='coerce')
            if pct >= 15: s += 15; reasons.append(f"🔥 Trainer Hot")
        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 12; reasons.append("🏇 Elite Jockey")
    except: pass
    return s, reasons

def get_market_move(r_data):
    current = float(r_data.get('sp_dec') or 1.0)
    morning = float(r_data.get('morning_price_dec') or current)
    if current < morning * 0.95: return "🔥 STEAMER"
    if current > morning * 1.05: return "❄️ DRIFTER"
    return "📊 STABLE"

def get_tissue_price(score):
    return round(100 / (score + 12), 2)

# --- 3. DATA OPS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except:
    conn = None

# --- 4. INTERFACE ---
st.sidebar.header("🕹️ Strategy Mode")
app_mode = st.sidebar.radio("Active Engine:", ["Value Strategy", "Elite Performance"])

st.sidebar.divider()
st.sidebar.header("🛡️ Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
min_score = st.sidebar.slider("Min Value Score", 0, 60, 20)
min_gap = st.sidebar.slider("Min Gap % Filter", -100, 100, -100)

st.sidebar.divider()
st.sidebar.subheader("🔍 Browser Tools")
show_all_races = st.sidebar.toggle("Show ALL Racecards", value=True)

# CRITICAL: Initialize session state if not present
if 'all_races' not in st.session_state: st.session_state.all_races = []
if 'value_horses' not in st.session_state: st.session_state.value_horses = []

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Analyzing Every Runner..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                st.session_state.all_races = r.json().get('racecards', [])
                
                # We clear and rebuild the list every time the button is clicked
                new_picks = []
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    if code_filter != "All Codes" and cat != code_filter: continue
                    
                    for r_data in race.get('runners', []):
                        score, reasons = get_advanced_score(r_data)
                        odds = float(r_data.get('sp_dec') or 1.0)
                        tissue = get_tissue_price(score)
                        gap = round(((odds - tissue) / tissue) * 100, 1)
                        
                        is_match = False
                        if app_mode == "Value Strategy":
                            if odds >= 4.0 and score >= min_score: is_match = True
                        else:
                            if odds < 4.0 and score >= 15: is_match = True
                        
                        if is_match and gap >= min_gap:
                            new_picks.append({
                                "Horse": r_data.get('horse'), "Course": race.get('course'),
                                "Time": race.get('off_time'), "Odds": odds, "Score": score,
                                "Tissue": tissue, "Gap": f"{gap}%", "Move": get_market_move(r_data),
                                "Tag": "VALUE" if odds >= 4.0 else "BANKER", "Analysis": " | ".join(reasons)
                            })
                st.session_state.value_horses = new_picks

    # 🟢 TOP SELECTIONS (This part was disappearing)
    if st.session_state.value_horses:
        st.subheader(f"🎯 Qualifying Selections ({len(st.session_state.value_horses)})")
        # Ensure we always show the current selections in the state
        picks = st.session_state.value_horses
        for i in range(0, len(picks), 4):
            cols = st.columns(4)
            for j, h in enumerate(picks[i:i+4]):
                with cols[j]:
                    color = "#FFD700" if h['Tag'] == "VALUE" else "#00FFCC"
                    st.markdown(f"""<div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; min-height:280px; margin-bottom:10px;">
                        <h3 style='margin:0;'>{h['Horse']}</h3><b>{h['Time']} {h['Course']}</b><hr style='border-color:black;'>
                        <b>Price: {h['Odds']}</b> | Fair: {h['Tissue']}<br>
                        <b>Gap: {h['Gap']}</b> | {h['Move']}<br>
                        <small>{h['Analysis']}</small></div>""", unsafe_allow_html=True)

    # 🏁 FULL BROWSER
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Racecard Browser")
        for race in st.session_state.all_races:
            cat = get_race_category(race)
            if code_filter != "All Codes" and cat != code_filter: continue
            
            # Highlight any horse that exists in our current session_state picks
            race_picks = [p for p in st.session_state.value_horses if p['Time'] == race['off_time'] and p['Course'] == race['course']]
            
            if show_all_races or race_picks:
                with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({cat}) {'⭐' if race_picks else ''}"):
                    for r in race.get('runners', []):
                        s, _ = get_advanced_score(r)
                        is_p = any(p['Horse'] == r.get('horse') for p in race_picks)
                        style = "color: green; font-weight: bold;" if is_p else "color: gray;"
                        st.markdown(f"<span style='{style}'>{r.get('horse')}</span> | Score: {s} | Odds: {r.get('sp_dec')}", unsafe_allow_html=True)
