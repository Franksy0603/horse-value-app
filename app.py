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

st.set_page_config(page_title="Value Finder Pro V7.1", layout="wide")

# --- 2. ENGINES (Categorization & Scoring) ---
def get_race_category(race):
    is_jumps = race.get('jumps', '')
    race_type = str(race.get('type', '')).lower()
    surface = str(race.get('surface', '')).upper()
    if is_jumps and len(str(is_jumps).strip()) > 0: return "Jumps"
    if "flat" in race_type:
        return "Flat (AW)" if ("AW" in surface or "STANDARD" in surface) else "Flat (Turf)"
    return "Flat (Turf)"

def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    is_elite, is_hot = False, False
    try:
        if str(r_data.get('form', '')).endswith('1'): 
            s += 15; reasons.append("✅ LTO Winner")
        if 'CD' in str(r_data.get('cd', '')).upper(): 
            s += 10; reasons.append("🎯 C&D")
        t_stats = r_data.get('trainer_14_days', {})
        if isinstance(t_stats, dict) and pd.to_numeric(t_stats.get('percent', 0), errors='coerce') >= 20: 
            s += 15; reasons.append("🔥 Trainer Hot"); is_hot = True
        jky = str(r_data.get('jockey', ''))
        if any(elite in jky for elite in ELITE_JOCKEYS):
            s += 10; reasons.append("🏇 Elite Jockey"); is_elite = True
        if '1' in str(r_data.get('headgear', '')):
            s += 10; reasons.append("🎭 1st Headgear")
    except: pass
    return s, reasons, is_elite, is_hot

# --- 3. MARKET QUANT LOGIC ---
def get_market_move(r_data):
    current = float(r_data.get('sp_dec') or 1.0)
    morning = float(r_data.get('morning_price_dec') or current)
    if current < morning * 0.95: return "🔥 STEAMER"
    if current > morning * 1.05: return "❄️ DRIFTER"
    return "📊 STABLE"

def get_tissue_price(score):
    return round(100 / (score + 12), 2)

# --- 4. DATA OPERATIONS ---
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
    if ledger.empty: return "Ledger empty."
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
        if updates > 0: conn.update(spreadsheet=GSHEET_URL, data=ledger)
        return f"Settled {updates} bets!"
    return "No results yet."

# --- 5. INTERFACE ---
st.title("🏇 Value Finder Pro V7.1")

# SIDEBAR (RESTORING ALL FILTERS)
st.sidebar.header("🕹️ Strategy Mode")
app_mode = st.sidebar.radio("Engine:", ["Value Strategy", "Elite Performance"])

st.sidebar.divider()
st.sidebar.header("🛡️ Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
min_score = st.sidebar.slider("Min Value Score", 0, 60, 30)
min_gap = st.sidebar.slider("Min Value Gap %", -50, 100, 10)
stake_input = st.sidebar.number_input("Base Stake (£)", value=5)

st.sidebar.divider()
st.sidebar.subheader("🔍 Browser Settings")
hide_non_selection = st.sidebar.toggle("Hide Races Without Picks", value=True)

# Session States
if 'value_horses' not in st.session_state: st.session_state.value_horses = []
if 'all_races' not in st.session_state: st.session_state.all_races = []

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Analyzing Market Data..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                data = r.json()
                st.session_state.all_races = data.get('racecards', [])
                st.session_state.value_horses = []
                
                for race in st.session_state.all_races:
                    cat = get_race_category(race)
                    if code_filter != "All Codes" and cat != code_filter: continue
                    
                    num_r = len(race.get('runners', []))
                    hcap = "Handicap" in str(race.get('race_name', ''))
                    places = 2 if num_r < 5 else (3 if num_r < 8 else (4 if hcap and num_r >= 16 else 3))

                    for r_data in race.get('runners', []):
                        score, reasons, is_e, is_h = get_advanced_score(r_data, race)
                        odds = float(r_data.get('sp_dec') or 1.0)
                        tissue = get_tissue_price(score)
                        gap = round(((odds - tissue) / tissue) * 100, 1)
                        move = get_market_move(r_data)
                        
                        # MATCH LOGIC
                        if app_mode == "Value Strategy":
                            match = (score >= min_score and odds >= 5.0 and gap >= min_gap)
                            tag = "🏆 VALUE PLAY"
                        else:
                            match = (odds < 5.0 and (is_e or is_h) and score >= 20)
                            tag = "⚡ ELITE BANKER"

                        if match:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'), "Course": race.get('course'),
                                "Time": race.get('off_time'), "Odds": odds, "Score": score,
                                "Tissue": tissue, "Gap": f"{gap}%", "Move": move,
                                "Tag": tag, "Analysis": reasons, "Category": cat, "Places": places
                            })

    # ACTION CARDS
    if st.session_state.value_horses:
        st.subheader("🎯 Actionable Selection Cards")
        vcols = st.columns(min(len(st.session_state.value_horses), 4))
        for i, h in enumerate(st.session_state.value_horses[:4]):
            with vcols[i]:
                color = "#FFD700" if "VALUE" in h['Tag'] else "#00FFCC"
                st.markdown(f"""
                <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; min-height:300px;">
                    <h3 style='margin:0;'>{h['Horse']}</h3>
                    <b>{h['Time']} - {h['Course']}</b><br><small>{h['Category']}</small><hr style='border-color:black;'>
                    <b>{h['Tag']}</b><br>
                    Win: {h['Odds']} | Fair: {h['Tissue']}<br>
                    <b>Gap: {h['Gap']}</b> | <b>{h['Move']}</b><br>
                    <div style="background-color:rgba(255,255,255,0.4); padding:5px; border-radius:5px; margin-top:10px; font-size:0.85em;">
                        {' | '.join(h['Analysis'])}
                    </div>
                </div>""", unsafe_allow_html=True)
        
        if st.button("📤 LOG ALL TO SHEETS"):
            ledger = load_ledger()
            new_rows = pd.DataFrame(st.session_state.value_horses)
            for col in ["Result", "Pos", "P/L"]: new_rows[col] = "Pending"
            updated = pd.concat([ledger, new_rows], ignore_index=True).drop_duplicates(subset=['Horse', 'Date'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.balloons()

    # RESTORED DETAILED BROWSER
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        for race in st.session_state.all_races:
            cat = get_race_category(race)
            if code_filter != "All Codes" and cat != code_filter: continue
            
            # Show only races with picks if toggled
            has_pick = any(any(p['Horse'] == r.get('horse') and p['Time'] == race.get('off_time') for p in st.session_state.value_horses) for r in race.get('runners', []))
            if hide_non_selection and not has_pick: continue

            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} ({cat})"):
                for r in race.get('runners', []):
                    s, reasons, is_e, is_h = get_advanced_score(r, race)
                    o = float(r.get('sp_dec') or 1.0)
                    is_p = any(p['Horse'] == r.get('horse') and p['Time'] == race.get('off_time') for p in st.session_state.value_horses)
                    style = "color: #008000; font-weight: bold;" if is_p else "color: gray;"
                    st.markdown(f"<span style='{style}'>{r.get('horse')}</span> | Score: {s} | Odds: {o} | {', '.join(reasons)}", unsafe_allow_html=True)

with tab2:
    if st.button("🔄 SETTLE PENDING BETS"):
        st.toast(settle_ledger())
    st.dataframe(load_ledger(), use_container_width=True)
