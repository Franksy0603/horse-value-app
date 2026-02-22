import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime, timedelta
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
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            df.columns = [str(c).strip() for c in df.columns]
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L"])

# --- 3. RECONCILE LOGIC (Enhanced Precision & Diagnostics) ---
def clean_txt(text):
    if not text: return ""
    # 1. Remove text in brackets (e.g., (IRE), (AW), (GB))
    text = re.sub(r'\(.*?\)', '', str(text))
    # 2. Remove all non-alphanumeric characters (keep spaces)
    text = re.sub(r'[^A-Za-z0-9\s]', '', text)
    # 3. Standardize whitespace and uppercase
    return " ".join(text.split()).upper().strip()

def process_reconciliation(data):
    """Processes JSON results to update ledger with detailed matching."""
    results_map = {}
    api_sample_keys = [] # For diagnostics
    
    for race in data.get('results', []):
        course = clean_txt(race.get('course', ''))
        for runner in race.get('runners', []):
            horse = clean_txt(runner.get('horse', ''))
            pos = str(runner.get('position', ''))
            key = f"{course}|{horse}"
            results_map[key] = pos
            api_sample_keys.append(key)

    df = load_ledger()
    if df.empty: 
        st.error("Could not load ledger.")
        return

    # Ensure settlement columns exist
    for col in ['Pos', 'Result', 'P/L']:
        if col not in df.columns: df[col] = "-"

    match_count = 0
    mismatch_details = []

    for i, row in df.iterrows():
        # Only process bets marked as Pending
        if str(row.get('Result', '')).strip().title() == 'Pending':
            c_cleaned = clean_txt(row.get('Course'))
            h_cleaned = clean_txt(row.get('Horse'))
            lookup_key = f"{c_cleaned}|{h_cleaned}"
            
            if lookup_key in results_map:
                final_pos = results_map[lookup_key]
                df.at[i, 'Pos'] = final_pos
                if final_pos == '1':
                    df.at[i, 'Result'] = 'Winner'
                    odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1
                    df.at[i, 'P/L'] = odds - 1
                else:
                    df.at[i, 'Result'] = 'Loser'
                    df.at[i, 'P/L'] = -1.0
                match_count += 1
            else:
                mismatch_details.append(f"❓ No match for **{row.get('Horse')}** at {row.get('Course')} (Key: `{lookup_key}`)")

    if match_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Settled {match_count} bets!")
        st.rerun()
    else:
        st.sidebar.warning("No matches found.")
        with st.expander("🔍 Why did reconciliation fail?"):
            st.write("The script checked the API results but couldn't find matches for these 'Pending' bets:")
            for item in mismatch_details:
                st.write(item)
            st.markdown("---")
            st.write("### API Data Sample")
            st.write("The API is providing these keys (Course|Horse):")
            st.write(api_sample_keys[:15])
            st.info("If the names above look different from your ledger (e.g., 'Kempton Park' vs 'Kempton'), that is the cause.")

# --- 4. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_input = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10, step=1)

def display_sidebar_stats(s_val):
    df = load_ledger()
    if not df.empty:
        if 'Stake' not in df.columns: df['Stake'] = s_val
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake'] = pd.to_numeric(df['Stake'], errors='coerce').fillna(0)
        
        total_profit = (df['P/L'] * df['Stake']).sum()
        total_invested = df['Stake'].sum()
        
        pl_color = "green" if total_profit >= 0 else "red"
        st.sidebar.markdown(f"### Total Profit: :{pl_color}[£{total_profit:,.2f}]")
        
        c1, c2 = st.sidebar.columns(2)
        c1.metric("Invested", f"£{total_invested}")
        if total_invested > 0:
            roi = (total_profit / total_invested) * 100
            c2.metric("ROI", f"{roi:.1f}%")
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔄 Reconcile Results")
        
        uploaded_file = st.sidebar.file_uploader("Upload Results JSON", type=["json"])
        if uploaded_file and st.sidebar.button("🚀 Sync Uploaded File"):
            process_reconciliation(json.load(uploaded_file))
        
        st.sidebar.markdown("OR")
        
        if st.sidebar.button("🔄 Auto Reconcile (Last 48 Hours)"):
            auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
            combined_data = {"results": []}
            # Specifically check Today and Yesterday standard results
            for days_ago in [0, 1]:
                date_str = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
                r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={date_str}", auth=auth)
                if r.status_code == 200:
                    combined_data["results"].extend(r.json().get('results', []))
            
            if combined_data["results"]:
                process_reconciliation(combined_data)
            else:
                st.sidebar.error("API returned no results for this period.")
    else:
        st.sidebar.info("Ledger is empty.")

display_sidebar_stats(stake_input)

# --- 5. SCORING ENGINE ---
def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and str(sp_val).replace('.','',1).isdigit(): return float(sp_val)
    odds_list = runner.get('odds', [])
    prices = [float(e.get('decimal')) for e in odds_list if e.get('decimal') not in ['-', 'SP', '', None]]
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
        if r.status_code == 200:
            races = r.json().get('racecards', [])
            st.session_state.all_races = races
            st.session_state.value_horses = []
            
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
                            "Pos": "-",
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
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            filtered = new_df[~new_df['Horse'].isin(ledger['Horse'])]
            if not filtered.empty:
                updated_df = pd.concat([ledger, filtered], ignore_index=True)
                conn.update(spreadsheet=GSHEET_URL, data=updated_df)
                st.balloons()
                st.success(f"Successfully logged {len(filtered)} bets!")
                st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'),
                "Score": get_score(r),
                "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP",
                "Value": "💎 YES" if (get_score(r) >= min_score and get_best_odds(r) >= 5.0) else ""
            } for r in race.get('runners', [])]))
