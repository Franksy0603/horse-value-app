import streamlit as st
import pandas as pd
import requests
import json
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & SECRETS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Automated Ledger")

if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 2. SECURE CONNECTION ---
try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
    st.sidebar.success("🔒 Secure API Linked")
except Exception as e:
    st.sidebar.error(f"❌ Connection Error: {str(e)}")
    conn = None

def load_ledger():
    if conn and GSHEET_URL:
        try:
            return conn.read(spreadsheet=GSHEET_URL, ttl=0)
        except:
            pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "P/L"])

# --- 3. UPDATED: SMART JSON RESULT MATCHER ---
def upload_json_data():
    st.sidebar.markdown("---")
    st.sidebar.subheader("📂 Smart Results Update")
    uploaded_file = st.sidebar.file_uploader("Upload API Results JSON", type=["json"])
    
    if uploaded_file is not None:
        try:
            file_data = json.load(uploaded_file)
            all_winners = []

            # Extract winners from JSON results
            if isinstance(file_data, dict) and 'results' in file_data:
                for race in file_data['results']:
                    course_name = str(race.get('course', '')).upper().strip()
                    for runner in race.get('runners', []):
                        if str(runner.get('position')) == '1':
                            horse_name = str(runner.get('horse', '')).upper().strip()
                            all_winners.append(f"{course_name}|{horse_name}")

            if st.sidebar.button("🚀 Update My Pending Bets"):
                df = load_ledger()
                match_count = 0
                
                # We only want to update horses currently in the spreadsheet marked 'Pending'
                for index, row in df.iterrows():
                    if str(row['Result']).strip().title() == 'Pending':
                        c_name = str(row['Course']).upper().strip()
                        h_name = str(row['Horse']).upper().strip()
                        lookup_key = f"{c_name}|{h_name}"
                        
                        if lookup_key in all_winners:
                            df.at[index, 'Result'] = 'Winner'
                            # Ensure Odds is a float for P/L calculation
                            odds = float(row['Odds']) if row['Odds'] else 1.0
                            df.at[index, 'P/L'] = odds - 1
                            match_count += 1
                        else:
                            # Logic: If the race date is in the past, it's a loser
                            try:
                                race_date = datetime.strptime(str(row['Date']), "%Y-%m-%d").date()
                                if race_date < datetime.now().date():
                                    df.at[index, 'Result'] = 'Loser'
                                    df.at[index, 'P/L'] = -1.0
                                    match_count += 1
                            except: continue

                if match_count > 0:
                    conn.update(spreadsheet=GSHEET_URL, data=df)
                    st.sidebar.success(f"✅ Updated {match_count} existing bets!")
                    st.rerun()
                else:
                    st.sidebar.warning("No matching pending bets found in this file.")
        except Exception as e:
            st.sidebar.error(f"JSON Error: {e}")

# --- 4. DASHBOARD & RECONCILE ---
def reconcile_results():
    # Standard API reconciliation logic
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
    if r.status_code == 200:
        # (Logic omitted for brevity, same as previous version)
        pass

st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10, step=1)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty:
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake'] = pd.to_numeric(df.get('Stake', s_val), errors='coerce').fillna(s_val)
        total_money_pl = (df['P/L'] * df['Stake']).sum()
        total_invested = df['Stake'].sum()
        
        pl_color = "green" if total_money_pl >= 0 else "red"
        st.sidebar.markdown(f"### Total Profit: :{pl_color}[£{total_money_pl:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested}")
        if total_invested > 0:
            c2.metric("ROI", f"{(total_money_pl / total_invested) * 100:.1f}%")
        
        st.sidebar.markdown("---")
        upload_json_data()
    else:
        st.sidebar.info("Ledger is empty.")
        upload_json_data()

display_sidebar_stats(stake_input)

# --- 5. DATA PROCESSING & INTERFACE ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and str(sp_val).replace('.','',1).isdigit(): return float(sp_val)
    prices = [float(e.get('decimal')) for e in runner.get('odds', []) if str(e.get('decimal', '')).replace('.','',1).isdigit()]
    return max(prices) if prices else 0.0

def get_score(h):
    s = 0
    if str(h.get('form', '')).endswith('1'): s += 15
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            if float(t_stats.get('percent', 0)) > 20: s += 15
        except: pass
    return s

st.sidebar.markdown("---")
min_score = st.sidebar.slider("Min Value Score", 0, 50, 20, 5)

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing today's value..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for r_data in race.get('runners', []):
                    odds, score = get_best_odds(r_data), get_score(r_data)
                    if score >= min_score and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'), "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')), "Odds": odds,
                            "Score": score, "Stake": stake_input, "Result": "Pending", "P/L": 0.0
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 GOLD VALUE BETS")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            st.markdown(f'<div style="background-color:#FFD700; padding:20px; border-radius:10px; border:2px solid #DAA520; text-align:center; color:#000;"><h2>{h["Horse"]}</h2><p><b>{h["Time"]} - {h["Course"]}</b></p><hr><b>Score: {h["Score"]}</b><br>Odds: {int(h["Odds"]-1)}/1</div>', unsafe_allow_html=True)
    
    if st.button("📤 LOG SELECTIONS"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        filtered = new_df[~new_df['Horse'].isin(ledger['Horse'])]
        if not filtered.empty:
            conn.update(spreadsheet=GSHEET_URL, data=pd.concat([ledger, filtered], ignore_index=True))
            st.balloons()
            st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
            st.table(pd.DataFrame([{"Horse": r.get('horse'), "Score": get_score(r), "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP", "Value": "💎 YES" if (get_score(r) >= min_score and get_best_odds(r) >= 5.0) else ""} for r in race.get('runners', [])]))
