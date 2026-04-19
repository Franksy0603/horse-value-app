import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
import plotly.express as px
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & CONFIG ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

st.set_page_config(page_title="Value Finder Pro V8.2", layout="wide")

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

def get_tissue_price(score):
    return round(100 / (score + 12), 2)

# --- 3. DATA OPS ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except:
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip().title() for c in df.columns]
            if not df.empty and 'P/L' not in df.columns: df['P/L'] = 0.0
            if 'P/L' in df.columns:
                df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
            return df
        except: pass
    return pd.DataFrame()

# --- 4. INTERFACE ---
st.sidebar.header("🕹️ Strategy Mode")
app_mode = st.sidebar.radio("Active Engine:", ["Value Strategy", "Elite Performance"])

st.sidebar.divider()
st.sidebar.header("🛡️ Settings")
min_score = st.sidebar.slider("Min Value Score", 0, 60, 20)
min_gap = st.sidebar.slider("Min Gap % Filter", -100, 100, -100)
show_all_races = st.sidebar.toggle("Show ALL Racecards", value=True)

if 'all_races' not in st.session_state: st.session_state.all_races = []
if 'value_horses' not in st.session_state: st.session_state.value_horses = []

tab1, tab2, tab3 = st.tabs(["🚀 Analysis", "📊 Ledger", "📈 ROI Dashboard"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Analyzing Market..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                st.session_state.all_races = r.json().get('racecards', [])
                picks = []
                for race in st.session_state.all_races:
                    for r_data in race.get('runners', []):
                        score, reasons = get_advanced_score(r_data)
                        odds = float(r_data.get('sp_dec') or 1.0)
                        tissue = get_tissue_price(score)
                        gap = round(((odds - tissue) / tissue) * 100, 1)
                        is_match = (app_mode == "Value Strategy" and odds >= 4.0 and score >= min_score) or \
                                   (app_mode == "Elite Performance" and odds < 4.0 and score >= 15)
                        if is_match and gap >= min_gap:
                            picks.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'), "Course": race.get('course'),
                                "Time": race.get('off_time'), "Odds": odds, "Score": score,
                                "Gap": f"{gap}%", "Tag": app_mode, "Analysis": " | ".join(reasons),
                                "Result": "Pending", "Pos": "-", "P/L": 0.0
                            })
                st.session_state.value_horses = picks

    # 🟢 FIXED CARD GRID LOGIC
    if st.session_state.value_horses:
        st.subheader(f"🎯 Qualifying {app_mode} Selections")
        picks = st.session_state.value_horses
        
        # We loop in chunks of 4 and handle the column index safely
        for i in range(0, len(picks), 4):
            cols = st.columns(4)
            for j in range(4):
                if i + j < len(picks):
                    h = picks[i + j]
                    with cols[j]:
                        color = "#FFD700" if h['Tag'] == "Value Strategy" else "#00FFCC"
                        st.markdown(f"""<div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; margin-bottom:10px;">
                            <h3 style='margin:0;'>{h['Horse']}</h3><b>{h['Time']} {h['Course']}</b><br>
                            <b>Odds: {h['Odds']}</b> | Gap: {h['Gap']}</div>""", unsafe_allow_html=True)
        
        if st.button("📤 Log to Ledger"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date', 'Time'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Ledger Updated!")

    # Full Browser
    if st.session_state.all_races:
        st.divider()
        for race in st.session_state.all_races:
            has_p = any(p['Horse'] == r['horse'] and p['Time'] == race['off_time'] for p in st.session_state.value_horses for r in race['runners'])
            if show_all_races or has_p:
                with st.expander(f"🕒 {race['off_time']} - {race['course']} {'⭐' if has_p else ''}"):
                    for r in race['runners']:
                        s, _ = get_advanced_score(r)
                        is_sel = any(p['Horse'] == r['horse'] and p['Time'] == race['off_time'] for p in st.session_state.value_horses)
                        style = "color: green; font-weight: bold;" if is_sel else "color: gray;"
                        st.markdown(f"<span style='{style}'>{r['horse']}</span> | Score: {s} | Odds: {r.get('sp_dec')}", unsafe_allow_html=True)

with tab2:
    ledger_df = load_ledger()
    if not ledger_df.empty:
        st.dataframe(ledger_df, use_container_width=True)
    else:
        st.info("No data in Ledger.")

with tab3:
    st.header("📈 ROI Dashboard")
    df = load_ledger()
    if not df.empty and 'Result' in df.columns:
        valid_bets = df[df['Result'].str.lower().isin(['winner', 'loser'])].copy()
        if not valid_bets.empty:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Bets", len(valid_bets))
            m2.metric("Strike Rate", f"{(len(valid_bets[valid_bets['Result'].str.lower() == 'winner'])/len(valid_bets)*100):.1f}%")
            m3.metric("Total P/L", f"{valid_bets['P/L'].sum():.2f} pts")
            
            # Graph safety: Only show if we have 2+ points
            if len(valid_bets) > 1:
                valid_bets['Cumulative'] = valid_bets['P/L'].cumsum()
                fig = px.line(valid_bets, y='Cumulative', title="Profit Growth")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Settle some bets as 'Winner' or 'Loser' to see stats.")
