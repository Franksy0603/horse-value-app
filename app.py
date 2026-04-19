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

st.set_page_config(page_title="Value Finder Pro V8.8", layout="wide")

# --- 2. ENGINES ---
def get_race_category(race):
    is_jumps = race.get('jumps', '')
    race_type = str(race.get('type', '')).lower()
    surface = str(race.get('surface', '')).upper()
    if is_jumps and len(str(is_jumps).strip()) > 0: return "Jumps"
    if "flat" in race_type:
        return "Flat (AW)" if ("AW" in surface or "STANDARD" in surface) else "Flat (Turf)"
    return "Flat (Turf)"

def get_advanced_score(r_data, race_going):
    s = 0
    reasons = []
    try:
        form = str(r_data.get('form', ''))
        if form.endswith('1'): 
            s += 15; reasons.append("✅ LTO Winner")
        cd = str(r_data.get('cd', '')).upper()
        if 'C' in cd: s += 10; reasons.append("🎯 Course Form")
        if 'D' in cd: s += 5; reasons.append("🏁 Distance Form")
        current_g = str(race_going).upper()
        past_g = str(r_data.get('going', '')).upper()
        if len(current_g) > 2 and current_g in past_g:
            s += 5; reasons.append("🌍 Ground Match")
    except:
        pass 
    return s, reasons

def get_tissue_price(score):
    return round(100 / (max(score, 0) + 12), 2)

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
            return df
        except: pass
    return pd.DataFrame()

# --- 4. INTERFACE ---
st.sidebar.header("🕹️ Strategy Mode")
app_mode = st.sidebar.radio("Active Engine:", ["Value Strategy", "Elite Performance"])

st.sidebar.divider()
st.sidebar.header("🛡️ Settings")
min_score = st.sidebar.slider("Min Value Score", 0, 60, 0) # Set to 0 for maximum visibility
min_gap = st.sidebar.slider("Min Gap % Filter", -100, 100, -100)
show_all_races = st.sidebar.toggle("Show ALL Racecards", value=True)

if 'all_races' not in st.session_state: st.session_state.all_races = []
if 'value_horses' not in st.session_state: st.session_state.value_horses = []

tab1, tab2, tab3 = st.tabs(["🚀 Analysis", "📊 Ledger", "📈 Stats"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Fetching Data..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                st.session_state.all_races = r.json().get('racecards', [])
                picks = []
                for race in st.session_state.all_races:
                    going = race.get('going', 'N/A')
                    for r_data in race.get('runners', []):
                        score, reasons = get_advanced_score(r_data, going)
                        odds = float(r_data.get('sp_dec') or 1.0)
                        tissue = get_tissue_price(score)
                        gap = round(((odds - tissue) / tissue) * 100, 1)
                        
                        # --- MODIFIED LOGIC GATE ---
                        is_match = False
                        if app_mode == "Value Strategy":
                            # Removed the odds >= 4.0 requirement so you can see SP (1.0) horses tonight
                            if score >= min_score and gap >= min_gap: 
                                is_match = True
                        else:
                            # Elite Mode
                            if odds < 4.0 and score >= min_score: 
                                is_match = True
                        
                        if is_match:
                            picks.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'), "Course": race.get('course'),
                                "Time": race.get('off_time'), "Odds": odds, "Score": score,
                                "Gap": f"{gap}%", "Tag": app_mode, "Analysis": " | ".join(reasons)
                            })
                st.session_state.value_horses = picks
            else:
                st.error(f"API Error: {r.status_code}")

    if st.session_state.all_races:
        c1, c2 = st.columns(2)
        c1.metric("Races Scanned", len(st.session_state.all_races))
        c2.metric("Qualifiers Found", len(st.session_state.value_horses))

    if st.session_state.value_horses:
        st.divider()
        for h in st.session_state.value_horses:
            color = "#FFD700" if h['Tag'] == "Value Strategy" else "#00FFCC"
            st.markdown(f"""
            <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; margin-bottom:10px;">
                <span style="font-size:1.1em; font-weight:bold;">{h['Horse']}</span> - {h['Time']} {h['Course']}<br>
                <b>Odds: {h['Odds']}</b> | Score: {h['Score']} | Gap: {h['Gap']}<br>
                <small>{h['Analysis'] if h['Analysis'] else 'No specific trends found'}</small>
            </div>
            """, unsafe_allow_html=True)
        
        if st.button("📤 Log Selections"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            new_df['Result'] = 'Pending'
            new_df['P/L'] = 0.0
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date', 'Time'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Logged!")

    if st.session_state.all_races:
        st.divider()
        for race in st.session_state.all_races:
            race_picks = [p['Horse'] for p in st.session_state.value_horses if p['Time'] == race['off_time'] and p['Course'] == race['course']]
            if show_all_races or race_picks:
                with st.expander(f"🕒 {race['off_time']} - {race['course']} {'⭐' if race_picks else ''}"):
                    for r in race['runners']:
                        h_name = r.get('horse')
                        is_sel = h_name in race_picks
                        style = "color: green; font-weight: bold;" if is_sel else "color: gray;"
                        st.markdown(f"<span style='{style}'>{h_name}</span> | Odds: {r.get('sp_dec')}", unsafe_allow_html=True)

with tab2:
    st.dataframe(load_ledger(), use_container_width=True)

with tab3:
    st.header("📈 Strategy Stats")
    df = load_ledger()
    if not df.empty and 'Result' in df.columns:
        settled = df[df['Result'].str.lower().isin(['winner', 'loser'])].copy()
        if not settled.empty:
            m1, m2, m3 = st.columns(3)
            wins = len(settled[settled['Result'].str.lower() == 'winner'])
            m1.metric("Total Bets", len(settled))
            m2.metric("Strike Rate", f"{(wins/len(settled)*100):.1f}%")
            try:
                pl = pd.to_numeric(settled['P/L'], errors='coerce').sum()
                m3.metric("Total P/L", f"{pl:.2f} pts")
            except: pass
