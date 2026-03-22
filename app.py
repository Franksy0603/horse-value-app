import streamlit as st
import pandas as pd
import requests
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & DATA MAPS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

# Elite Jockeys (Statistically highest ROI)
ELITE_JOCKEYS = ["W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle", "B Curtis", "L Morris"]

# Track Direction Mapping 
COURSE_INFO = {
    "Kempton": "Right", "Wolverhampton": "Left", "Southwell": "Left", 
    "Chelmsford": "Left", "Lingfield": "Left", "Newcastle": "Straight",
    "Ascot": "Right", "Sandown": "Right", "Chester": "Left", "Epsom": "Left"
}

st.set_page_config(page_title="Value Finder Pro V4", layout="wide")
st.title("🏇 Value Finder Pro: Advanced Strategy Engine")

# --- 2. SIDEBAR STRATEGY ---
st.sidebar.header("🛡️ Strategy Settings")
strategy_mode = st.sidebar.selectbox(
    "Staking Strategy", 
    ["80/20 Split", "Flat Stake", "Weighted Score"],
    help="80/20: 80% Place / 20% Win. Flat: Same stake."
)

recon_date = st.sidebar.date_input("Reconciliation Date", datetime.now() - timedelta(days=1))
stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=10, step=1)

st.sidebar.markdown("---")
# Default set to 25 based on your "Lottery" observation 
min_score = st.sidebar.slider("Min Value Score", 0, 50, 25, 5)
hide_low_value = st.sidebar.checkbox("🔍 Show Value Only", value=False)

if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 3. DATABASE & UTILITY ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Secure API Linked")
except Exception as e:
    st.sidebar.error("❌ Connection Error")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip().title() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Market_Move"])

def clean_txt(text):
    if not text: return ""
    text = str(text).upper().strip()
    text = re.sub(r'\(.*?\)', '', text) 
    return " ".join(text.split())

# --- 4. ADVANCED SCORING ENGINE  ---
def get_advanced_score(r_data, race_data):
    s = 0
    reasons = []
    
    # Core Form
    form = str(r_data.get('form', ''))
    if form.endswith('1'): 
        s += 15
        reasons.append("✅ LTO Winner")
        
    # Trainer Form
    t_stats = r_data.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        win_pc = pd.to_numeric(t_stats.get('percent', 0), errors='coerce') or 0
        if win_pc > 20: 
            s += 15
            reasons.append("🔥 Trainer Hot (20%+)")
        elif win_pc > 10: 
            s += 5
            reasons.append("📈 Trainer Form")

    # Jockey Intent (Elite Bookings)
    jky = r_data.get('jockey', '')
    if any(elite in jky for elite in ELITE_JOCKEYS):
        s += 10
        reasons.append(f"🏇 Elite Jockey: {jky}")

    # Official Rating (OR) Handicap Sweet Spot
    current_or = pd.to_numeric(r_data.get('or', 0), errors='coerce') or 0
    if 45 <= current_or <= 75:
        s += 5
        reasons.append("⚖️ Prime Handicap Mark")

    # Surface Boost
    course_name = race_data.get('course', '')
    if "(AW)" in course_name:
        s += 5
        reasons.append("🌊 AW Specialist")

    return s, reasons

def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    return float(sp_val) if sp_val and str(sp_val).replace('.','',1).isdigit() else 0.0

# --- 5. MAIN ANALYSIS TAB ---
tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger"])

with tab1:
    if st.button('🚀 Run Multi-Factor Analysis'):
        with st.spinner("Scanning for Professional Signals..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                races = r.json().get('racecards', [])
                st.session_state.all_races = races
                st.session_state.value_horses = []
                
                for race in races:
                    for r_data in race.get('runners', []):
                        score, reasons = get_advanced_score(r_data, race)
                        odds = get_best_odds(r_data)
                        
                        if score >= min_score and odds >= 5.0:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time', race.get('off')),
                                "Odds": odds, "Score": score, "Stake": stake_input,
                                "Analysis": reasons, "Result": "Pending", "P/L": 0.0
                            })

    # High Value Selections (Golden Cards)
    if st.session_state.value_horses:
        st.subheader("🎯 Professional Grade Selections")
        v_cols = st.columns(3)
        sorted_val = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)
        
        for i, h in enumerate(sorted_val[:3]):
            with v_cols[i]:
                # Triple Signal Alert Color 
                box_color = "#FFD700" if h['Score'] >= 35 else "#f0f2f6"
                st.markdown(f"""<div style="background-color:{box_color}; padding:15px; border-radius:10px; color:#000; text-align:center; border:2px solid #000;">
                <h3>{h['Horse']}</h3><b>{h['Time']} - {h['Course']}</b><br>Score: {h['Score']}<br>Odds: {h['Odds']}</div>""", unsafe_allow_html=True)

        if st.button("📤 LOG SELECTIONS TO SHEETS"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses).drop(columns=['Analysis'])
            updated_df = pd.concat([ledger, new_df[~new_df['Horse'].isin(ledger['Horse'])]], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.balloons()

    # Detailed Racecards
    if st.session_state.all_races:
        st.divider()
        st.header("🏁 Detailed Race Analysis")
        for race in st.session_state.all_races:
            course = race.get('course', '')
            direction = next((v for k, v in COURSE_INFO.items() if k in course), "Unknown")
            
            with st.expander(f"🕒 {race.get('off_time')} - {course} ({direction}-Handed)"):
                for r in race.get('runners', []):
                    score, reasons = get_advanced_score(r, race)
                    odds = get_best_odds(r)
                    is_val = (score >= min_score and odds >= 5.0)
                    
                    if hide_low_value and not is_val: continue
                    
                    c1, c2, c3, c4 = st.columns([3, 1, 1, 4])
                    c1.write(f"**{r.get('horse')}**")
                    c2.write(f"Score: {score}")
                    c3.write(f"Odds: {odds}")
                    if is_val:
                        c4.info(" | ".join(reasons))

with tab2:
    ledger_df = load_ledger()
    st.subheader("Live Performance Ledger")
    st.dataframe(ledger_df, use_container_width=True)
