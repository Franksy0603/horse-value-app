import streamlit as st
import pandas as pd
import requests
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

# --- 3. RECONCILE (LIVE FEED METHOD) ---
def reconcile_results():
    df = load_ledger()
    if df.empty:
        st.sidebar.warning("Ledger is empty.")
        return

    pending_mask = df['Result'].str.strip().str.title() == 'Pending'
    pending_rows = df[pending_mask]
    
    if pending_rows.empty:
        st.sidebar.info("No 'Pending' bets found.")
        return

    st.sidebar.info(f"🔄 Fetching Live Results...")
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    all_winners = []

    # Bypassing the 422 Archive error by using the Live Feed
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
    
    if r.status_code == 200:
        results_data = r.json().get('results', [])
        for race in results_data:
            course_name = str(race.get('course', '')).upper().strip()
            for runner in race.get('runners', []):
                # Using 'position' as confirmed by your JSON file
                if str(runner.get('position')) == '1':
                    horse_name = str(runner.get('horse', '')).upper().strip()
                    all_winners.append(f"{course_name}|{horse_name}")
    else:
        st.sidebar.error(f"Live API unavailable (Error {r.status_code}).")
        return

    if not all_winners:
        st.sidebar.warning("No winners found in the live feed yet.")
        return

    match_count = 0
    today = datetime.now().date()
    
    for index, row in df.iterrows():
        if str(row['Result']).strip().title() == 'Pending':
            c_name = str(row['Course']).upper().strip()
            h_name = str(row['Horse']).upper().strip()
            lookup_key = f"{c_name}|{h_name}"
            
            if lookup_key in all_winners:
                df.at[index, 'Result'] = 'Winner'
                df.at[index, 'P/L'] = float(row['Odds']) - 1
                match_count += 1
            else:
                try:
                    race_date = datetime.strptime(str(row['Date']), "%Y-%m-%d").date()
                    if race_date < today:
                        df.at[index, 'Result'] = 'Loser'
                        df.at[index, 'P/L'] = -1.0
                        match_count += 1
                except:
                    continue
        
    if match_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Settled {match_count} bets!")
        st.rerun()

# --- 4. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10, step=1)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty:
        if 'Stake' not in df.columns:
            df['Stake'] = s_val
            
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake'] = pd.to_numeric(df['Stake'], errors='coerce').fillna(0)
        
        df['Money_PL'] = df['P/L'] * df['Stake']
        total_money_pl = df['Money_PL'].sum()
        total_invested = df['Stake'].sum()
        
        pl_color = "green" if total_money_pl >= 0 else "red"
        st.sidebar.markdown(f"### Total Profit: :{pl_color}[£{total_money_pl:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested}")
        if total_invested > 0:
            roi = (total_money_pl / total_invested) * 100
            c2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        if st.sidebar.button("🔄 Reconcile Yesterday's Bets"):
            reconcile_results()
    else:
        st.sidebar.info("Ledger is empty.")

display_sidebar_stats(stake_input)

# --- 5. DATA PROCESSING ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and str(sp_val).replace('.','',1).isdigit():
        return float(sp_val)
    odds_list = runner.get('odds', [])
    prices = []
    if isinstance(odds_list, list):
        for e in odds_list:
            val = e.get('decimal')
            if val is not None and str(val) not in ['-', 'SP', 'None', '']:
                try: prices.append(float(val))
                except: continue
    return max(prices) if prices else 0.0

def get_score(h):
    s = 0
    form = str(h.get('form', ''))
    if form.endswith('1'): s += 15
    t_stats = h.get('trainer_14_days', {})
    if isinstance(t_stats, dict):
        try:
            win_pc = float(t_stats.get('percent', 0))
            if win_pc > 20: s += 15
            elif win_pc > 10: s += 5
        except: pass
    return s

# --- 6. MAIN INTERFACE ---
st.sidebar.markdown("---")
st.sidebar.header("⚙️ Analysis Controls")
min_score = st.sidebar.slider("Min Value Score", 0, 50, 20, 5)

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing today's value..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        races = r.json().get('racecards', [])
        st.session_state.all_races = races
        st.session_state.value_horses = []
        
        if races:
            for race in races:
                for r_data in race.get('runners', []):
                    odds = get_best_odds(r_data)
                    score = get_score(r_data)
                    if score >= min_score and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'),
                            "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')),
                            "Odds": odds,
                            "Score": score,
                            "Stake": stake_input,
                            "Result": "Pending",
                            "P/L": 0.0
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 GOLD VALUE BETS")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            st.markdown(f"""
            <div style="background-color:#FFD700; padding:20px; border-radius:10px; border:2px solid #DAA520; text-align:center; color:#000;">
                <h2 style="margin:0; color:#000;">{h['Horse']}</h2>
                <p style="margin:5px 0; font-size:16px;"><b>{h['Time']} - {h['Course']}</b></p>
                <hr style="border-top: 1px solid #DAA520;">
                <p style="font-size:20px; margin:5px;"><b>Score: {h['Score']}</b></p>
                <p style="font-size:18px; margin:0;">Odds: {int(h['Odds']-1) if h['Odds'] > 1 else 'SP'}/1</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("📤 LOG ALL SELECTIONS TO GOOGLE SHEETS"):
        if conn:
            try:
                ledger = load_ledger()
                new_df = pd.DataFrame(st.session_state.value_horses)
                filtered = new_df[~new_df['Horse'].isin(ledger['Horse'])]
                if not filtered.empty:
                    updated_df = pd.concat([ledger, filtered], ignore_index=True)
                    conn.update(spreadsheet=GSHEET_URL, data=updated_df)
                    st.balloons()
                    st.success(f"Successfully logged {len(filtered)} bets!")
                    st.rerun()
                else:
                    st.info("Today's horses are already in the ledger.")
            except Exception as e:
                st.error(f"Logging Failed: {e}")

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'),
                "Score": get_score(r),
                "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP",
                "Value": "💎 YES" if (get_score(r) >= min_score and get_best_odds(r) >= 5.0) else ""
            } for r in race.get('runners', [])]))
