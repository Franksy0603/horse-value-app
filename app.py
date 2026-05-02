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

st.set_page_config(page_title="Value Finder Pro V10.2", layout="wide")

# --- 2. ENGINES ---
def calculate_minimum_price(score):
    """If score is 0, any price is fine (1.1). Otherwise, calculate required odds."""
    if score <= 0:
        return 1.1
    # Example: Score 20 -> 5.0, Score 50 -> 2.0
    return round(100 / score, 2)

def get_simple_score(r_data):
    s = 0
    reasons = []
    form = str(r_data.get('form', ''))
    if form.endswith('1'): 
        s += 30; reasons.append("✅ LTO Winner")
    cd = str(r_data.get('cd', '')).upper()
    if 'CD' in cd: s += 30; reasons.append("🎯 Course & Distance")
    elif 'C' in cd: s += 15; reasons.append("🏁 Course Form")
    elif 'D' in cd: s += 15; reasons.append("🏁 Distance Form")
    return s, reasons

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
min_score_input = st.sidebar.slider("Min Value Score", 0, 100, 0)
odds_floor_input = st.sidebar.slider("Minimum Odds Filter", 1.1, 20.0, 1.1)

if 'all_races' not in st.session_state: st.session_state.all_races = []
if 'value_horses' not in st.session_state: st.session_state.value_horses = []

tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Connecting to API..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            
            if r.status_code == 200:
                st.session_state.all_races = r.json().get('racecards', [])
                picks = []
                total_runners_scanned = 0
                
                for race in st.session_state.all_races:
                    for r_data in race.get('runners', []):
                        total_runners_scanned += 1
                        score, reasons = get_simple_score(r_data)
                        min_p = calculate_minimum_price(score)
                        odds = float(r_data.get('sp_dec') or 1.0)
                        
                        # Logic Gate
                        is_match = False
                        if app_mode == "Value Strategy":
                            # Must meet score AND odds must be higher than our calculated min price
                            if score >= min_score_input and odds >= min_p and odds >= odds_floor_input:
                                is_match = True
                        else: # Elite Performance
                            # Simply look for high scores regardless of value gap
                            if score >= min_score_input and score > 0:
                                is_match = True
                        
                        if is_match:
                            picks.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time'),
                                "Odds": odds,
                                "Score": score,
                                "Min Price": min_p,
                                "Tag": app_mode,
                                "Analysis": " | ".join(reasons) if reasons else "No specific trends"
                            })
                
                st.session_state.value_horses = picks
                st.info(f"Scan Complete: Checked {total_runners_scanned} horses across {len(st.session_state.all_races)} races.")
            else:
                st.error(f"API Error: {r.status_code}. Check your secrets/credentials.")

    # Display results
    if st.session_state.value_horses:
        for h in st.session_state.value_horses:
            color = "#FFD700" if h['Tag'] == "Value Strategy" else "#00FFCC"
            st.markdown(f"""
            <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:1px solid #333; margin-bottom:10px;">
                <span style="font-size:1.1em; font-weight:bold;">{h['Horse']}</span> - {h['Time']} {h['Course']}<br>
                <b>Odds: {h['Odds']}</b> | Score: {h['Score']} | Target Price: {h['Min Price']}<br>
                <small>{h['Analysis']}</small>
            </div>
            """, unsafe_allow_html=True)
        
        if st.button("📤 Log to Sheets"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            new_df['Result'] = 'Pending'; new_df['P/L'] = 0.0
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date', 'Time'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Successfully logged!")
    elif st.session_state.all_races:
        st.warning("No horses met your current filter settings. Try lowering the 'Min Value Score'.")

with tab2:
    st.dataframe(load_ledger(), use_container_width=True)
