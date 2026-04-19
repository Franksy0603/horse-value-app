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

st.set_page_config(page_title="Value Finder Pro V8.5", layout="wide")

# --- 2. ENGINES (Added Going/Ground Logic) ---
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
    # Core Logic
    if str(r_data.get('form', '')).endswith('1'): 
        s += 15; reasons.append("✅ LTO Winner")
    if 'C' in str(r_data.get('cd', '')).upper(): 
        s += 10; reasons.append("🎯 Course Form")
    
    # Ground/Going Logic (New)
    past_going = str(r_data.get('going', '')).upper()
    current_going = str(race_going).upper()
    if current_going in past_going and len(current_going) > 2:
        s += 5; reasons.append("🌍 Ground Match")
        
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

tab1, tab2, tab3 = st.tabs(["🚀 Analysis", "📊 Ledger", "📈 Stats"])

with tab1:
    if st.button('🚀 Run Analysis'):
        with st.spinner("Finding Value..."):
            auth = HTTPBasicAuth(API_USER, API_PASS)
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                st.session_state.all_races = r.json().get('racecards', [])
                picks = []
                for race in st.session_state.all_races:
                    going = race.get('going', 'Unknown')
                    for r_data in race.get('runners', []):
                        score, reasons = get_advanced_score(r_data, going)
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
                                "Gap": f"{gap}%", "Tag": app_mode, "Analysis": " | ".join(reasons)
                            })
                st.session_state.value_horses = picks

    # 🟢 Safe List Display (Vertical Bars instead of Grid to prevent IndexError)
    if st.session_state.value_horses:
        st.subheader(f"🎯 Current {app_mode} Selections")
        for h in st.session_state.value_horses:
            color = "#FFD700" if h['Tag'] == "Value Strategy" else "#00FFCC"
            st.markdown(f"""
            <div style="background-color:{color}; padding:15px; border-radius:10px; color:#000; border:2px solid #333; margin-bottom:10px;">
                <span style="font-size:1.2em; font-weight:bold;">{h['Horse']}</span> - {h['Time']} {h['Course']}<br>
                <b>Odds: {h['Odds']}</b> | Score: {h['Score']} | <b>Gap: {h['Gap']}</b><br>
                <small>{h['Analysis']}</small>
            </div>
            """, unsafe_allow_html=True)
        
        if st.button("📤 Log Selections"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            new_df['Result'] = 'Pending'
            new_df['P/L'] = 0.0
            updated = pd.concat([ledger, new_df], ignore_index=True).drop_duplicates(subset=['Horse', 'Date', 'Time'])
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Successfully logged to Sheets!")

with tab2:
    st.dataframe(load_ledger(), use_container_width=True)

with tab3:
    st.header("📈 Strategy Stats")
    df = load_ledger()
    if not df.empty and 'Result' in df.columns:
        # Filter for settled bets only
        settled = df[df['Result'].str.lower().isin(['winner', 'loser'])].copy()
        if not settled.empty:
            # Simple Columnar metrics
            m1, m2, m3 = st.columns(3)
            total_bets = len(settled)
            wins = len(settled[settled['Result'].str.lower() == 'winner'])
            # Attempt P/L calculation if column exists
            try:
                pl = pd.to_numeric(settled['P/L'], errors='coerce').sum()
                m3.metric("Total P/L", f"{pl:.2f} pts")
            except:
                m3.metric("Total P/L", "N/A")
            
            m1.metric("Total Bets", total_bets)
            m2.metric("Strike Rate", f"{(wins/total_bets*100):.1f}%")
        else:
            st.info("No winners/losers marked in Ledger yet.")
    else:
        st.info("Stats will appear once the Ledger has 'Result' data.")
