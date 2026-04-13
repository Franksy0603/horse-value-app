import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & CONFIGURATION ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

st.set_page_config(page_title="Value Finder Pro V7.0", layout="wide")

# --- 2. PRECISION ENGINES (Categorization & Scoring) ---
def get_race_category(race):
    is_jumps_data = race.get('jumps', '')
    race_type = str(race.get('type', '')).lower()
    surface = str(race.get('surface', '')).upper()
    if is_jumps_data and len(str(is_jumps_data).strip()) > 0:
        return "Jumps"
    if "flat" in race_type:
        return "Flat (AW)" if ("AW" in surface or "STANDARD" in surface) else "Flat (Turf)"
    return "Flat (Turf)"

def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    is_elite_jky, is_hot_trn = False, False
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15; reasons.append("✅ LTO Winner")
        if 'CD' in str(r_data.get('cd', '')).upper(): 
            s += 10; reasons.append("🎯 C&D")
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict) and pd.to_numeric(t_stats.get('percent', 0), errors='coerce') >= 20: 
            s += 15; reasons.append("🔥 Trainer Hot"); is_hot_trn = True
        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 10; reasons.append("🏇 Elite Jockey"); is_elite_jky = True
        if '1' in str(r_data.get('headgear', '')):
            s += 10; reasons.append("🎭 1st Headgear")
    except: pass
    return s, reasons, is_elite_jky, is_hot_trn

# --- 3. QUANT LOGIC (Market Heat & Tissue Pricing) ---
def get_market_move(r_data):
    current = float(r_data.get('sp_dec') or (r_data.get('odds', [{}])[0].get('decimal', 1.0)))
    morning = float(r_data.get('morning_price_dec') or current)
    if current < morning * 0.9: return "🔥 STEAMER"
    if current > morning * 1.1: return "❄️ DRIFTER"
    return "📊 STABLE"

def get_tissue_price(score):
    """Calculates Fair Odds: Higher score = Lower Fair Price."""
    return round(100 / (score + 12), 2)

# --- 4. DATA OPERATIONS & AUTO-SETTLE ---
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
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Result", "Pos", "P/L"])

def settle_ledger():
    ledger = load_ledger()
    if ledger.empty: return "No data in ledger."
    auth = HTTPBasicAuth(API_USER, API_PASS)
    date_str = datetime.now().strftime("%Y-%m-%d")
    r = requests.get(f"{BASE_URL}/results", params={'date': date_str}, auth=auth)
    
    if r.status_code == 200:
        results = r.json().get('results', [])
        res_map = {f"{res['course'].upper()}|{run['horse'].upper()}": run for res in results for run in res.get('runners', [])}
        updates = 0
        for i, row in ledger.iterrows():
            if str(row.get('Result', '')).lower() == 'pending':
                key = f"{str(row['Course']).upper()}|{str(row['Horse']).upper()}"
                if key in res_map:
                    pos = res_map[key].get('position')
                    ledger.at[i, 'Pos'] = pos
                    ledger.at[i, 'Result'] = 'Winner' if str(pos) == '1' else 'Loser'
                    ledger.at[i, 'P/L'] = (float(row['Odds']) - 1) if str(pos) == '1' else -1.0
                    updates += 1
        if updates > 0:
            conn.update(spreadsheet=GSHEET_URL, data=ledger)
            return f"Settled {updates} bets!"
    return "No new results found."

# --- 5. INTERFACE ---
st.title("🏇 Value Finder Pro V7.0")
tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger & Auto-Settle"])

with tab1:
    st.sidebar.header("🕹️ Strategy Mode")
    app_mode = st.sidebar.radio("Active Engine:", ["Value Strategy", "Elite Performance"])
    min_gap = st.sidebar.slider("Min Value Gap %", -50, 100, 10)
    
    if st.button('🚀 Run Analysis'):
        with st.spinner("Calculating Quants..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                st.session_state.all_races = r.json().get('racecards', [])
                st.session_state.value_horses = []
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    for r_data in race.get('runners', []):
                        score, reasons, is_e, is_h = get_advanced_score(r_data, race)
                        odds = float(r_data.get('sp_dec') or 1.0)
                        tissue = get_tissue_price(score)
                        gap = round(((odds - tissue) / tissue) * 100, 1)
                        
                        match = (app_mode == "Value Strategy" and odds >= 5.0 and gap >= min_gap) or \
                                (app_mode == "Elite Performance" and odds < 5.0 and (is_e or is_h))
                        
                        if match:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'), "Course": race.get('course'),
                                "Time": race.get('off_time'), "Odds": odds, "Tissue": tissue,
                                "Gap": f"{gap}%", "Move": get_market_move(r_data),
                                "Score": score, "Analysis": reasons, "Category": cat
                            })

    if 'value_horses' in st.session_state and st.session_state.value_horses:
        vcols = st.columns(4)
        for i, h in enumerate(st.session_state.value_horses[:4]):
            with vcols[i]:
                st.markdown(f"""
                <div style="background-color:#1e1e1e; padding:15px; border-radius:10px; border:2px solid #FFD700;">
                    <h3 style='margin:0; color:#FFD700;'>{h['Horse']}</h3>
                    <b>{h['Time']} {h['Course']}</b><br>
                    <hr>
                    <b>Odds: {h['Odds']}</b> (Fair: {h['Tissue']})<br>
                    <b>Value Gap:</b> <span style='color:#00FF00;'>{h['Gap']}</span><br>
                    <b>Move:</b> {h['Move']}<br>
                    <small>{' | '.join(h['Analysis'])}</small>
                </div>""", unsafe_allow_html=True)

with tab2:
    if st.button("🔄 SETTLE PENDING BETS"):
        st.write(settle_ledger())
    st.dataframe(load_ledger(), use_container_width=True)
