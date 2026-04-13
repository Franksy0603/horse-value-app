import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import re
from streamlit_gsheets import GSheetsConnection

# --- 1. CONFIG & SYSTEM SETUP ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

# Pro Jockey List
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris", "S Levey"]

st.set_page_config(page_title="Value Finder Pro V7.5", layout="wide")

# --- 2. THE MASTER SCORING ENGINE ---
def get_advanced_score(runner, race):
    score = 0
    reasons = []
    
    # 1. Recent Form (Last Time Out Winner)
    form = str(runner.get('form', ''))
    if form.endswith('1'):
        score += 15
        reasons.append("✅ LTO Winner")
    
    # 2. Course and Distance
    cd = str(runner.get('cd', '')).upper()
    if 'CD' in cd:
        score += 15
        reasons.append("🎯 C&D Specialist")
    elif 'C' in cd:
        score += 7
        reasons.append("📍 Course Winner")
    
    # 3. Trainer Performance (14-Day Strike Rate)
    t_stats = runner.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        pct = pd.to_numeric(t_stats.get('percent', 0), errors='coerce')
        if pct >= 20:
            score += 15
            reasons.append(f"🔥 Trainer Hot ({int(pct)}%)")
        elif pct >= 15:
            score += 8
            reasons.append("📈 Trainer Steady")
            
    # 4. Elite Jockey Signal
    jky = str(runner.get('jockey', ''))
    if any(elite in jky for elite in ELITE_JOCKEYS):
        score += 12
        reasons.append("🏇 Elite Jockey")

    # 5. Gear Changes
    if '1' in str(runner.get('headgear', '')):
        score += 10
        reasons.append("🎭 1st Time Gear")

    return score, reasons

# --- 3. MARKET DYNAMICS (Quants) ---
def get_market_move(runner):
    # Current vs Morning Price
    curr = float(runner.get('sp_dec') or (runner.get('odds', [{}])[0].get('decimal', 1.0)))
    morning = float(runner.get('morning_price_dec') or curr)
    
    if curr < morning * 0.90: return "🔥 STEAMER", "#ff4b4b"
    if curr > morning * 1.10: return "❄️ DRIFTER", "#3399ff"
    return "📊 STABLE", "#808495"

def get_tissue_price(score):
    # Professional 'Tissue' formula: Odds = 100 / (Score + Confidence Factor)
    return round(100 / (score + 15), 2)

# --- 4. DATA OPERATIONS (Google Sheets) ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except:
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
        df.columns = [str(c).strip().title() for c in df.columns]
        return df
    return pd.DataFrame()

def log_to_sheets(new_data):
    current_ledger = load_ledger()
    updated_df = pd.concat([current_ledger, pd.DataFrame(new_data)], ignore_index=True)
    updated_df = updated_df.drop_duplicates(subset=['Horse', 'Date', 'Time'])
    conn.update(spreadsheet=GSHEET_URL, data=updated_df)
    return True

# --- 5. THE APP INTERFACE ---
st.sidebar.title("Settings & Strategy")
app_mode = st.sidebar.radio("Selection Mode", ["Value Strategy (5.0+)", "Elite Performance (<5.0)"])
min_score = st.sidebar.slider("Min Score Filter", 0, 70, 30)
min_gap = st.sidebar.slider("Min Value Gap %", -100, 100, -20)
show_all = st.sidebar.toggle("Show ALL Racecards", value=False)

tab1, tab2 = st.tabs(["🚀 Live Market Analysis", "📊 Betting Ledger"])

with tab1:
    if st.button("🚀 Run Full Pro Analysis"):
        auth = HTTPBasicAuth(API_USER, API_PASS)
        with st.spinner("Fetching Live API Data..."):
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                st.session_state.races = r.json().get('racecards', [])
                st.session_state.picks = []
                
                for race in st.session_state.races:
                    for runner in race.get('runners', []):
                        score, reasons = get_advanced_score(runner, race)
                        odds = float(runner.get('sp_dec') or 1.0)
                        tissue = get_tissue_price(score)
                        gap = round(((odds - tissue) / tissue) * 100, 1)
                        move, move_color = get_market_move(runner)
                        
                        # Selection Logic
                        is_val = (app_mode == "Value Strategy (5.0+)" and odds >= 5.0 and score >= min_score)
                        is_eli = (app_mode == "Elite Performance (<5.0)" and odds < 5.0 and score >= 20)
                        
                        if (is_val or is_eli) and gap >= min_gap:
                            st.session_state.picks.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": runner.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time'),
                                "Odds": odds,
                                "Score": score,
                                "Tissue": tissue,
                                "Gap": f"{gap}%",
                                "Move": move,
                                "Color": move_color,
                                "Analysis": " | ".join(reasons),
                                "Result": "Pending",
                                "P/L": 0.0
                            })

    # DISPLAY CARDS
    if 'picks' in st.session_state and st.session_state.picks:
        st.subheader(f"🎯 Qualifying {app_mode} Selections")
        cols = st.columns(4)
        for i, pick in enumerate(st.session_state.picks):
            with cols[i % 4]:
                st.markdown(f"""
                <div style="border: 2px solid #333; padding: 15px; border-radius: 10px; background-color: #0e1117; margin-bottom: 10px;">
                    <h3 style="margin:0; color:#FFD700;">{pick['Horse']}</h3>
                    <p style="margin:0; font-size: 0.9em;">{pick['Time']} {pick['Course']}</p>
                    <hr style="margin: 10px 0;">
                    <b>Price: {pick['Odds']}</b> <small>(Tissue: {pick['Tissue']})</small><br>
                    <b>Gap: <span style="color:#00ff00;">{pick['Gap']}</span></b><br>
                    <b>Market: <span style="color:{pick['Color']};">{pick['Move']}</span></b><br>
                    <p style="font-size: 0.8em; margin-top:10px; color:#aaa;">{pick['Analysis']}</p>
                </div>
                """, unsafe_allow_html=True)
        
        if st.button("📤 Log These Selections to Ledger"):
            if log_to_sheets(st.session_state.picks):
                st.success("✅ Logged to Google Sheets!")

    # BROWSER SECTION
    if 'races' in st.session_state:
        st.divider()
        st.header("🏁 Full Race Browser")
        for race in st.session_state.races:
            has_pick = any(p['Horse'] == r['horse'] and p['Time'] == race['off_time'] for p in st.session_state.picks for r in race['runners'])
            if show_all or has_pick:
                with st.expander(f"🕒 {race['off_time']} - {race['course']} {'⭐' if has_pick else ''}"):
                    for r in race['runners']:
                        s, _ = get_advanced_score(r, race)
                        o = float(r.get('sp_dec') or 1.0)
                        is_sel = any(p['Horse'] == r['horse'] for p in st.session_state.picks)
                        name_display = f"**{r['horse']}**" if is_sel else r['horse']
                        st.write(f"{name_display} | Score: {s} | Odds: {o}")

with tab2:
    st.subheader("📊 Your Betting History")
    df_ledger = load_ledger()
    if not df_ledger.empty:
        st.dataframe(df_ledger, use_container_width=True)
    else:
        st.info("No bets logged yet.")
