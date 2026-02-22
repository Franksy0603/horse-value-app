import streamlit as st
import pd as pd
import pd
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
            if df is not None:
                df.columns = [str(c).strip() for c in df.columns]
                for col in ["P/L", "Stake", "Odds"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0 if col != "Odds" else 1.0)
                return df
        except Exception as e:
            st.error(f"⚠️ Sheet Load Error: {e}")
    return pd.DataFrame()

# --- 3. RECONCILE LOGIC WITH DIAGNOSTICS ---
def clean_txt(text):
    if not text: return ""
    # Remove text in brackets, non-alphanumeric, and extra spaces
    text = re.sub(r'\(.*?\)', '', str(text))
    text = re.sub(r'[^A-Za-z0-9\s]', '', text)
    return " ".join(text.split()).upper().strip()

def process_reconciliation(data):
    try:
        results_map = {}
        api_sample = []
        
        # Parse JSON
        for race in data.get('results', []):
            course = clean_txt(race.get('course', ''))
            for runner in race.get('runners', []):
                horse = clean_txt(runner.get('horse', ''))
                key = f"{course}|{horse}"
                results_map[key] = str(runner.get('position', ''))
                api_sample.append(key)

        df = load_ledger()
        if df.empty:
            st.error("Could not load Ledger.")
            return

        settled_count = 0
        missed_matches = []

        for i, row in df.iterrows():
            res_val = str(row.get('Result', '')).strip().upper()
            if res_val in ['PENDING', '-', '']:
                l_course = clean_txt(row.get('Course'))
                l_horse = clean_txt(row.get('Horse'))
                lookup_key = f"{l_course}|{l_horse}"
                
                if lookup_key in results_map:
                    pos = results_map[lookup_key]
                    df.at[i, 'Pos'] = pos
                    if pos == '1':
                        df.at[i, 'Result'] = 'Winner'
                        df.at[i, 'P/L'] = float(row.get('Odds', 1)) - 1.0
                    else:
                        df.at[i, 'Result'] = 'Loser'
                        df.at[i, 'P/L'] = -1.0
                    settled_count += 1
                else:
                    missed_matches.append(lookup_key)

        if settled_count > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.success(f"✅ Successfully settled {settled_count} bets!")
            st.rerun()
        else:
            st.warning("⚠️ No matches found between your file and the Ledger.")
            with st.expander("🔍 Diagnostic Report: Why did it fail?"):
                st.write("**What your Sheet is looking for:**")
                st.write(missed_matches[:10])
                st.write("**What the Uploaded File contains (Sample):**")
                st.write(api_sample[:10])
                st.info("Check if the Course names match exactly. If your sheet says 'NEWCASTLE' and the file says 'NEWCASTLE AW', they will not match.")

    except Exception as e:
        st.error(f"Critical error during processing: {e}")

# --- 4. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_val = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats():
    try:
        df = load_ledger()
        if not df.empty:
            profit = (df['P/L'] * df['Stake']).sum()
            invested = df['Stake'].sum()
            color = "green" if profit >= 0 else "red"
            st.sidebar.markdown(f"### Profit: :{color}[£{profit:,.2f}]")
            
            c1, c2 = st.sidebar.columns(2)
            c1.metric("Invested", f"£{invested:,.0f}")
            roi = (profit / invested * 100) if invested > 0 else 0
            c2.metric("ROI", f"{roi:.1f}%")
            
            st.sidebar.markdown("---")
            st.sidebar.subheader("🔄 Reconcile Results")
            
            uploaded_file = st.sidebar.file_uploader("Upload Results JSON", type=["json"])
            if uploaded_file:
                if st.sidebar.button("🚀 Process Uploaded File"):
                    process_reconciliation(json.load(uploaded_file))

            if st.sidebar.button("🔄 Auto-Sync (Today/Yesterday)"):
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                combined = {"results": []}
                for day in [0, 1]:
                    d_str = (datetime.now() - timedelta(days=day)).strftime("%Y-%m-%d")
                    r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={d_str}", auth=auth)
                    if r.status_code == 200: 
                        combined["results"].extend(r.json().get('results', []))
                process_reconciliation(combined)
    except Exception as e:
        st.sidebar.error(f"Stats Error: {e}")

display_sidebar_stats()

# --- 5 & 6. SCORING & INTERFACE ---
def get_best_odds(runner):
    sp = runner.get('sp_dec')
    if sp and str(sp).replace('.','',1).isdigit(): return float(sp)
    prices = [float(e.get('decimal')) for e in runner.get('odds', []) if str(e.get('decimal')).replace('.','',1).isdigit()]
    return max(prices) if prices else 0.0

def get_score(h):
    s = 0
    if str(h.get('form', '')).endswith('1'): s += 15
    try:
        win_pc = float(h.get('trainer_14_days', {}).get('percent', 0))
        if win_pc > 20: s += 15
        elif win_pc > 10: s += 5
    except: pass
    return s

if st.button('🚀 Run Analysis'):
    with st.spinner("Finding value..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
        if r.status_code == 200:
            st.session_state.all_races = r.json().get('racecards', [])
            st.session_state.value_horses = []
            for race in st.session_state.all_races:
                for r_data in race.get('runners', []):
                    odds, score = get_best_odds(r_data), get_score(r_data)
                    if score >= 20 and odds >= 5.0:
                        st.session_state.value_horses.append({
                            "Date": datetime.now().strftime("%Y-%m-%d"),
                            "Horse": r_data.get('horse'),
                            "Course": race.get('course'),
                            "Time": race.get('off_time', race.get('off')),
                            "Odds": odds, "Score": score, "Stake": stake_val,
                            "Result": "Pending", "Pos": "-", "P/L": 0.0
                        })

if st.session_state.value_horses:
    st.markdown("### 🏆 Gold Bets")
    cols = st.columns(min(3, len(st.session_state.value_horses)))
    for i, h in enumerate(st.session_state.value_horses[:3]):
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
    if st.button("📤 Log All Selections"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        if not ledger.empty:
            new_df = new_df[~new_df.apply(lambda x: ((ledger['Horse'] == x['Horse']) & (ledger['Course'] == x['Course'])).any(), axis=1)]
        if not new_df.empty:
            updated = pd.concat([ledger, new_df], ignore_index=True)
            conn.update(spreadsheet=GSHEET_URL, data=updated)
            st.success("Logged!")
            st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('course')} - {race.get('off_time', 'Race')}"):
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'), "Score": get_score(r),
                "Odds": f"{int(get_best_odds(r)-1)}/1" if get_best_odds(r) > 1 else "SP"
            } for r in race.get('runners', [])]))
