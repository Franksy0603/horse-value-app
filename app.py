import streamlit as st
import pandas as pd
import requests
import re
import json
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & SECRETS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Advanced Strategy Engine")

# --- 2. SIDEBAR STRATEGY & SETTINGS ---
st.sidebar.header("🛡️ Strategy Settings")
strategy_mode = st.sidebar.selectbox(
    "Staking Strategy", 
    ["80/20 Split", "Flat Stake", "Weighted Score"],
    help="80/20: 80% Place / 20% Win. Flat: Same stake. Weighted: Score-based sizing."
)

recon_date = st.sidebar.date_input("Reconciliation Date", datetime.now() - timedelta(days=1))
use_surface_boost = st.sidebar.checkbox("Apply All-Weather (AW) Boost", value=True)
stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=10, step=1)

st.sidebar.markdown("---")
min_score = st.sidebar.slider("Min Value Score", 0, 50, 20, 5)
hide_low_value = st.sidebar.checkbox("🔍 Show Value Only", value=False)

if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 3. DATABASE CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Secure API Linked")
except Exception as e:
    st.sidebar.error(f"❌ Connection Error: {str(e)}")
    conn = None

def load_ledger():
    """Loads ledger and forces header consistency to prevent KeyError."""
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            # Force all headers to Title Case and remove hidden spaces
            df.columns = [str(c).strip().title() for c in df.columns]
            
            required_cols = ["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Market_Move"]
            for col in required_cols:
                if col not in df.columns:
                    df[col] = 0.0 if col in ["P/L", "Market_Move", "Stake"] else "Pending"
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Market_Move"])

def clean_txt(text):
    if not text: return ""
    text = str(text).upper().strip()
    text = re.sub(r'\(.*?\)', '', text) 
    text = re.sub(r'[^A-Z0-9\s]', '', text) 
    return " ".join(text.split())

# --- 4. AUTO-RECONCILE LOGIC ---
def process_reconciliation(api_data):
    results_map = {}
    for race in api_data.get('results', []):
        course = clean_txt(race.get('course', ''))
        for runner in race.get('runners', []):
            horse = clean_txt(runner.get('horse', ''))
            results_map[f"{course}|{horse}"] = {
                "pos": str(runner.get('position', '')),
                "sp": float(runner.get('sp_dec', 1.0))
            }

    df = load_ledger()
    if df.empty: return

    match_count = 0
    for i, row in df.iterrows():
        if str(row.get('Result', '')).strip() == 'Pending':
            key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
            
            if key in results_map:
                res = results_map[key]
                final_pos, sp = res["pos"], res["sp"]
                odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1
                stake = pd.to_numeric(row.get('Stake', 10), errors='coerce') or 10
                
                df.at[i, 'Market_Move'] = round(odds - sp, 2)
                df.at[i, 'Pos'] = final_pos
                
                if strategy_mode == "80/20 Split":
                    p_stake, w_stake = stake * 0.8, stake * 0.2
                    p_odds = ((odds - 1) / 4) + 1
                    if final_pos == '1':
                        df.at[i, 'Result'], df.at[i, 'P/L'] = 'Winner', round(((w_stake * odds) + (p_stake * p_odds)) - stake, 2)
                    elif final_pos in ['2', '3', '4']:
                        df.at[i, 'Result'], df.at[i, 'P/L'] = 'Placed', round((p_stake * p_odds) - stake, 2)
                    else:
                        df.at[i, 'Result'], df.at[i, 'P/L'] = 'Loser', -float(stake)
                else:
                    if final_pos == '1':
                        df.at[i, 'Result'], df.at[i, 'P/L'] = 'Winner', round((stake * odds) - stake, 2)
                    else:
                        df.at[i, 'Result'], df.at[i, 'P/L'] = 'Loser', -float(stake)
                match_count += 1

    if match_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Settled {match_count} bets!")
        st.rerun()

# --- 5. SCORING & ANALYSIS LOGIC ---
def get_score(h, is_aw=False):
    s = 0
    form = str(h.get('form', ''))
    if form.endswith('1'): s += 15
    if is_aw and use_surface_boost: s += 5
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            win_pc = pd.to_numeric(t_stats.get('percent', 0), errors='coerce') or 0
            if win_pc > 20: s += 15
            elif win_pc > 10: s += 5
        except: pass
    return s

def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and str(sp_val).replace('.','',1).isdigit(): return float(sp_val)
    odds_list = runner.get('odds', [])
    prices = [float(e.get('decimal')) for e in odds_list if str(e.get('decimal')).replace('.','',1).isdigit()]
    return max(prices) if prices else 0.0

# --- 6. APP TABS ---
tab1, tab2 = st.tabs(["🚀 Market Analysis", "📊 Ledger & Backup"])

with tab1:
    if st.button('🚀 Run Daily Analysis'):
        with st.spinner("Analyzing markets..."):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            r = requests.get(f"{BASE_URL}/racecards/standard", auth=auth)
            if r.status_code == 200:
                races = r.json().get('racecards', [])
                st.session_state.all_races = races
                st.session_state.value_horses = []
                for race in races:
                    is_aw = "(AW)" in race.get('course', '')
                    for r_data in race.get('runners', []):
                        odds = get_best_odds(r_data)
                        score = get_score(r_data, is_aw)
                        if score >= min_score and odds >= 5.0:
                            st.session_state.value_horses.append({
                                "Date": datetime.now().strftime("%Y-%m-%d"),
                                "Horse": r_data.get('horse'),
                                "Course": race.get('course'),
                                "Time": race.get('off_time', race.get('off')),
                                "Odds": odds, "Score": score, "Stake": stake_input,
                                "Result": "Pending", "Pos": "-", "P/L": 0.0, "Market_Move": 0.0
                            })

    # Show Golden Cards
    if st.session_state.value_horses:
        st.subheader("🏆 Top Value Selections")
        top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
        cols = st.columns(3)
        for i, h in enumerate(top_3):
            with cols[i]:
                st.markdown(f"""<div style="background-color:#FFD700; padding:15px; border-radius:10px; color:#000; text-align:center;">
                <h3>{h['Horse']}</h3><b>{h['Time']} - {h['Course']}</b><br>Score: {h['Score']}<br>Odds: {h['Odds']}</div>""", unsafe_allow_html=True)
        
        if st.button("📤 LOG TO SHEETS"):
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            updated_df = pd.concat([ledger, new_df[~new_df['Horse'].isin(ledger['Horse'])]], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated_df)
            st.success("Logged!")

with tab2:
    ledger_df = load_ledger()
    col_l, col_r = st.columns([4, 1])
    col_l.subheader("Live Ledger")
    
    # DOWNLOAD BUTTON
    csv = ledger_df.to_csv(index=False).encode('utf-8')
    col_r.download_button("📥 Download CSV", csv, "ledger_backup.csv", "text/csv")
    
    st.dataframe(ledger_df, use_container_width=True)

# SIDEBAR RECONCILE
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Auto Reconcile (Selected Date)"):
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    r = requests.get(f"{BASE_URL}/results", auth=auth, params={"date": recon_date.strftime("%Y-%m-%d")})
    if r.status_code == 200:
        process_reconciliation(r.json())
