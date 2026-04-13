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

st.set_page_config(page_title="Value Finder Pro V7.6", layout="wide")

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
    is_elite, is_hot = False, False
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15; reasons.append("✅ LTO Winner")
        if 'CD' in str(r_data.get('cd', '')).upper(): 
            s += 15; reasons.append("🎯 C&D")
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict) and pd.to_numeric(t_stats.get('percent', 0), errors='coerce') >= 20: 
            s += 15; reasons.append("🔥 Trainer Hot"); is_hot = True
        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 12; reasons.append("🏇 Elite Jockey"); is_elite = True
    except: pass
    return s, reasons, is_elite, is_hot

def get_market_move(r_data):
    current = float(r_data.get('sp_dec') or 1.0)
    morning = float(r_data.get('morning_price_dec') or current)
    if current < morning * 0.95: return "🔥 STEAMER"
    if current > morning * 1.05: return "❄️ DRIFTER"
    return "📊 STABLE"

def get_tissue_price(score):
    return round(100 / (score + 15), 2)

# --- 3. DATA OPERATIONS ---
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
    if ledger.empty: return "No data."
    auth = HTTPBasicAuth(API_USER, API_PASS)
    r = requests.get(f"{BASE_URL}/results", params={'date': datetime.now().strftime("%Y-%m-%d")}, auth=auth)
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
    return "No results found yet."

# --- 4. INTERFACE ---
st.sidebar.header("🕹️ Strategy Mode")
app_mode = st.sidebar.radio("Active Engine:", ["Value Strategy", "Elite Performance"])

st.sidebar.divider()
st.sidebar.header("🛡️ Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
min_score = st.sidebar.slider("Min Value Score", 0, 60, 30)
min_gap = st.sidebar.slider("Min Gap % Filter", -100, 100, -20)

st.sidebar.divider()
st.sidebar.subheader("🔍 Browser Tools")
show_all_races = st.sidebar.toggle("Show ALL Racecards", value=False)

# Initialize Session States to prevent KeyError
if 'value_horses' not in st.session_state: st.session_state.value_horses = []
if 'all_races' not in st.session_state: st.session_state.all_races = []

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Crunching data..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                st.session_state.all_races = r.json().get('racecards', [])
                st.session_state.value_horses = []
                
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    if code_filter != "All Codes" and cat != code_filter: continue
                    
                    for r_data in race.get('runners', []):
                        score, reasons, is_e, is_h = get_advanced_score(r_data)
                        odds = float(r_data.get('sp_dec') or 1.0)
                        tissue = get_tissue_price(score)
                        gap = round(((odds - tissue) / tissue) * 100, 1)
                        
                        is_match = (app_mode == "Value Strategy" and odds >= 5.0 and score >= min_score) or \
                                   (app_mode == "Elite Performance" and odds < 5.0 and score >= 20)
                        
                        if is_match and gap >= min_gap:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'), "Course": race.get('course'),
                                "Time": race.get('off_time'), "Odds": odds, "Score": score,
                                "Tissue": tissue, "Gap": f"{gap}%", "Move": get_market_move(r_data),
                                "Tag": "VALUE" if odds >= 5.0 else "BANKER", "Analysis": " | ".join(reasons)
                            })

    # TOP SELECTIONS (Unlimited Cards)
    if st.session_state.value_horses:
        st.subheader(f"🎯 Qualifying Selections ({len(st.session_state.value_horses)})")
        for i in range(0, len(st.session_state.value_horses), 4):
            cols = st.columns(4)
            for j, h in enumerate(st.session_state.value_horses[i:i+4]):
                with cols[j]:
                    color = "#FFD700" if h['Tag'] == "VALUE" else "#00FFCC"
                    st.markdown(f"""<div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; min-height:280px; margin-bottom:10px;">
                        <h3 style='margin:0;'>{h['Horse']}</h3><b>{h['Time']} {h['Course']}</b><hr style='border-color:black;'>
                        <b>Price: {h['Odds']}</b> | Fair: {h['Tissue']}<br>
                        <b>Gap: {h['Gap']}</b> | {h['Move']}<br>
                        <small>{h['Analysis']}</small></div>""", unsafe_allow_html=True)
        
        if st.button("📤 Log Picks to Sheets"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            for col in ["Result", "Pos", "P/L"]: new_df[col] = "Pending"
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date', 'Time'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Log Updated!")

    # FULL BROWSER
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Racecard Browser")
        for race in st.session_state.all_races:
            cat = get_race_category(race)
            if code_filter != "All Codes" and cat != code_filter: continue
            
            has_sel = any(any(p['Horse'] == r.get('horse') and p['Time'] == race.get('off_time') for p in st.session_state.value_horses) for r in race.get('runners', []))
            
            if show_all_races or has_sel:
                with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({cat}) {'⭐' if has_sel else ''}"):
                    for r in race.get('runners', []):
                        s, _, _, _ = get_advanced_score(r)
                        is_p = any(p['Horse'] == r.get('horse') and p['Time'] == race.get('off_time') for p in st.session_state.value_horses)
                        style = "color: green; font-weight: bold;" if is_p else "color: gray;"
                        st.markdown(f"<span style='{style}'>{r.get('horse')}</span> | Score: {s} | Odds: {r.get('sp_dec')}", unsafe_allow_html=True)

with tab2:
    if st.button("🔄 SETTLE PENDING BETS"):
        st.toast(settle_ledger())
    st.dataframe(load_ledger(), use_container_width=True)
