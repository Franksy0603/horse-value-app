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

st.set_page_config(page_title="Value Finder Pro V8.4", layout="wide")

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

    # --- NO-CRASH DISPLAY LOGIC ---
    if st.session_state.value_horses:
        st.subheader(f"🎯 Qualifying {app_mode} Selections")
        
        # We use standard Streamlit columns but wrapped in a simpler loop 
        # that doesn't rely on tuple assignment
        picks = st.session_state.value_horses
        
        # Display cards one by one in a predictable 4-wide pattern
        col_list = st.columns(4)
        for i, h in enumerate(picks):
            target_col = col_list[i % 4]
            with target_col:
                try:
                    color = "#FFD700" if h['Tag'] == "Value Strategy" else "#00FFCC"
                    st.markdown(f"""
                    <div style="background-color:{color}; padding:12px; border-radius:8px; color:#000; border:1px solid #333; margin-bottom:10px;">
                        <h4 style='margin:0;'>{h['Horse']}</h4>
                        <b>{h['Time']} {h['Course']}</b><br>
                        <b>Odds: {h['Odds']}</b> | Score: {h['Score']}<br>
                        <small style='font-size:0.75em;'>{h['Analysis']}</small>
                    </div>
                    """, unsafe_allow_html=True)
                except:
                    st.error("Error rendering card.")

        if st.button("📤 Log to Ledger"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date', 'Time'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Ledger Updated!")

    # --- BROWSER SECTION ---
    if st.session_state.all_races:
        st.divider()
        for race in st.session_state.all_races:
            # Safer way to check for highlighted horses
            sel_names = [p['Horse'] for p in st.session_state.value_horses if p['Time'] == race['off_time']]
            if show_all_races or sel_names:
                with st.expander(f"🕒 {race['off_time']} - {race['course']} {'⭐' if sel_names else ''}"):
                    for r in race['runners']:
                        h_name = r.get('horse')
                        is_sel = h_name in sel_names
                        style = "color: green; font-weight: bold;" if is_sel else "color: gray;"
                        st.markdown(f"<span style='{style}'>{h_name}</span> | Odds: {r.get('sp_dec')}", unsafe_allow_html=True)

with tab2:
    st.dataframe(load_ledger(), use_container_width=True)

with tab3:
    st.header("📈 ROI Dashboard")
    df = load_ledger()
    if not df.empty and 'Result' in df.columns and 'P/L' in df.columns:
        valid = df[df['Result'].str.lower().isin(['winner', 'loser'])].copy()
        if not valid.empty:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Bets", len(valid))
            m2.metric("Strike Rate", f"{(len(valid[valid['Result'].str.lower() == 'winner'])/len(valid)*100):.1f}%")
            m3.metric("Total P/L", f"{valid['P/L'].sum():.2f} pts")
