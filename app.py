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

st.set_page_config(page_title="Value Finder Pro V10.0", layout="wide")

# --- 2. BASIC ENGINES ---
def calculate_minimum_price(score):
    """Simple calculation for Minimum Acceptable Price based on score."""
    return round((1 / (score / 100)) + 0.1, 2) if score > 0 else 999.0

def get_simple_score(r_data):
    """Core metrics, returning a single integer score and a list of reasons."""
    s = 0
    reasons = []
    
    # 1. LTO Winner
    if str(r_data.get('form', '')).endswith('1'): 
        s += 30; reasons.append("✅ LTO Winner")
    
    # 2. Course/Distance (CD)
    cd = str(r_data.get('cd', '')).upper()
    if 'CD' in cd: s += 30; reasons.append("🎯 Course & Distance Form")
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
min_score = st.sidebar.slider("Min Value Score", 0, 100, 30)
odds_floor = st.sidebar.slider("Minimum Acceptable Odds (Decimal)", 1.1, 100.0, 1.1)

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
                picks = []
                for race in st.session_state.all_races:
                    for r_data in race.get('runners', []):
                        # 1. Calculate Simple Score
                        score, reasons = get_simple_score(r_data)
                        
                        # 2. Get Minimum Acceptable Price
                        min_price = calculate_minimum_price(score)
                        
                        # 3. Assess the Value based on simple logic
                        odds = float(r_data.get('sp_dec') or 1.0)
                        
                        is_match = False
                        if app_mode == "Value Strategy":
                            if odds >= min_price and score >= min_score and odds >= odds_floor: is_match = True
                        else:
                            # Simple Elite Check
                            if odds < 4.0 and score >= min_score: is_match = True
                        
                        if is_match:
                            picks.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'), "Course": race.get('course'),
                                "Time": race.get('off_time'), "Odds": odds, "Score": score,
                                "Min Price": min_price, "Tag": app_mode, "Analysis": " | ".join(reasons)
                            })
                st.session_state.value_horses = picks
            else:
                st.error(f"API Error: {r.status_code}")

    # Display Top Picks using simple color rows
    if st.session_state.value_horses:
        st.subheader(f"🎯 Qualifying {app_mode} Selections ({len(st.session_state.value_horses)})")
        for h in st.session_state.value_horses:
            color = "#D4AF37" if h['Tag'] == "Value Strategy" else "#2ECC71"
            st.markdown(f"""
            <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:1px solid #333; margin-bottom:10px;">
                <span style="font-size:1.1em; font-weight:bold;">{h['Horse']}</span> - {h['Time']} {h['Course']}<br>
                <b>Odds: {h['Odds']}</b> | Score: {h['Score']} | My Price: {h['Min Price']}<br>
                <small>{h['Analysis']}</small>
            </div>
            """, unsafe_allow_html=True)
        
        if st.button("📤 Log to Sheets"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            new_df['Result'] = 'Pending'
            new_df['P/L'] = 0.0
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date', 'Time'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Log Updated!")

with tab2:
    st.dataframe(load_ledger(), use_container_width=True)
