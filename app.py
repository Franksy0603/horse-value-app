import streamlit as st
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
from streamlit_gsheets import GSheetsConnection

# --- 1. CONFIGURATION ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

JUMPS_TRACKS = ["AINTREE", "ASCOT", "AYR", "CHELTENHAM", "HAYDOCK", "KEMPTON", "PUNCHESTOWN", "FAIRYHOUSE", "WETHERBY", "KELSO", "MUSSELBURGH", "UTTOXETER"]

st.set_page_config(page_title="Value Finder Pro V6.0", layout="wide")

# --- 2. DATA ENGINES ---
def get_race_category(race):
    surface = str(race.get('surface', '')).upper()
    course = str(race.get('course', '')).upper()
    is_jumps = str(race.get('jumps', '')).strip() != ""
    if "AW" in surface or "DUNDALK" in course or "WOLVERHAMPTON" in course:
        return "Flat (AW)"
    elif is_jumps or any(j in course for j in JUMPS_TRACKS):
        return "Jumps"
    return "Flat (Turf)"

def load_live_stats():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        df = conn.read(spreadsheet=GSHEET_URL)
        # Classification for stats
        df['Type'] = df['Course'].apply(lambda x: "Flat (AW)" if "AW" in str(x).upper() else ("Jumps" if any(j in str(x).upper() for j in JUMPS_TRACKS) else "Flat (Turf)"))
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        stats = df.groupby('Type')['P/L'].sum()
        return stats
    except:
        return None

# --- 3. HEADER & LIVE TRACKER ---
st.title("🏇 Value Finder Pro V6.0")

stats = load_live_stats()
if stats is not None:
    st.subheader("📊 Live Pot-Building Progress")
    m1, m2, m3 = st.columns(3)
    m1.metric("All-Weather P/L", f"£{stats.get('Flat (AW)', 0):.2f}", delta="Reliability Engine")
    m2.metric("Jumps P/L", f"£{stats.get('Jumps', 0):.2f}", delta="High Value Hunt")
    m3.metric("Turf P/L", f"£{stats.get('Flat (Turf)', 0):.2f}")
    st.divider()

# --- 4. SIDEBAR ---
st.sidebar.header("🛡️ Strategy Settings")
code_filter = st.sidebar.selectbox("Filter by Code", ["All Codes", "Flat (AW)", "Jumps", "Flat (Turf)"])
min_score = st.sidebar.slider("Min Value Score", 0, 60, 30, 5)
stake_input = st.sidebar.number_input("Total Stake (£)", value=5)

# --- 5. MAIN ANALYSIS ---
if st.button('🚀 Run Analysis'):
    with st.spinner("Calculating Value vs. Reliability..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
        
        if r.status_code == 200:
            selections = []
            for race in r.json().get('racecards', []):
                cat = get_race_category(race)
                if code_filter != "All Codes" and cat != code_filter: continue
                
                for r_data in race.get('runners', []):
                    # Scoring Logic
                    score = 0
                    if str(r_data.get('form', '')).endswith('1'): score += 15
                    if r_data.get('trainer_14_days', {}).get('percent', 0) >= 20: score += 15
                    
                    odds = float(r_data.get('sp_dec') or 1.0)
                    p_odds = round(((odds - 1) / 4) + 1, 2)
                    
                    if score >= min_score and odds >= 5.0:
                        selections.append({
                            "Horse": r_data.get('horse'),
                            "Time": race.get('off_time'),
                            "Course": race.get('course'),
                            "Odds": odds,
                            "Place_Odds": p_odds,
                            "Score": score,
                            "Category": cat
                        })
            st.session_state.current_picks = selections

# --- 6. SELECTION DISPLAY ---
if 'current_picks' in st.session_state and st.session_state.current_picks:
    st.subheader(f"🎯 Actionable Value: {code_filter}")
    cols = st.columns(3)
    
    for i, res in enumerate(st.session_state.current_picks):
        with cols[i % 3]:
            # Strategic Labeling (The Pivot)
            if res['Place_Odds'] < 2.0:
                tag, color, advice = "🥈 TOP 2 TARGET", "#E5E4E2", "Low T4 Value. Use Exchange Top 2."
            else:
                tag, color, advice = "🏆 80/20 VALUE", "#FFD700", "Good T4 Value. Bet E/W at Bet365."
                
            st.markdown(f"""
            <div style="background-color:{color}; padding:15px; border-radius:10px; border:2px solid #333; color:black;">
                <h3 style='margin:0;'>{res['Horse']}</h3>
                <b>{res['Time']} - {res['Course']}</b><br>
                <b>{tag}</b><br>
                <hr style='margin:10px 0; border-color:black;'>
                W: {res['Odds']} | P: {res['Place_Odds']} | Score: {res['Score']}<br>
                <small><i>{advice}</i></small>
            </div>""", unsafe_allow_html=True)
