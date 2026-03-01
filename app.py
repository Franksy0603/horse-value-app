import streamlit as st
import pandas as pd
import requests
import json
import re
from requests.auth import HTTPBasicAuth
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 1. SETTINGS & SECRETS ---
API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")

st.set_page_config(page_title="Value Finder Pro", layout="wide")
st.title("🏇 Value Finder Pro: Advanced Strategy Engine")

# --- 2. ADVANCED STRATEGY TOGGLES ---
st.sidebar.header("🛡️ Strategy Settings")
strategy_mode = st.sidebar.selectbox(
    "Staking Strategy", 
    ["Flat Stake", "80/20 Split", "Weighted Score"],
    help="Flat: Same stake. 80/20: Split Win/Place. Weighted: More on high scores."
)
use_surface_boost = st.sidebar.checkbox("Apply All-Weather (AW) Boost", value=True)
stake_input = st.sidebar.number_input("Base Stake (£)", min_value=1, value=10, step=1)

if 'value_horses' not in st.session_state:
    st.session_state.value_horses = []
if 'all_races' not in st.session_state:
    st.session_state.all_races = []

# --- 3. SECURE CONNECTION ---
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
            # --- FIX: Ensure new columns exist in the dataframe ---
            for col in ["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Market_Move"]:
                if col not in df.columns:
                    df[col] = 0.0 if col in ["P/L", "Market_Move", "Stake"] else "-"
            return df
        except: pass
    return pd.DataFrame(columns=["Date", "Horse", "Course", "Time", "Odds", "Score", "Stake", "Result", "Pos", "P/L", "Market_Move"])

def clean_txt(text):
    if not text: return ""
    return re.sub(r'\(.*?\)', '', str(text)).strip().upper()

# --- 4. ADVANCED RECONCILIATION ---
def process_reconciliation(data):
    results_map = {}
    for race in data.get('results', []):
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
        if str(row.get('Result', '')).strip().title() == 'Pending':
            key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
            
            if key in results_map:
                res = results_map[key]
                final_pos = res["pos"]
                sp = res["sp"]
                odds = pd.to_numeric(row.get('Odds', 1), errors='coerce') or 1
                stake = pd.to_numeric(row.get('Stake', 10), errors='coerce') or 10
                
                df.at[i, 'Market_Move'] = round(odds - sp, 2)
                df.at[i, 'Pos'] = final_pos
                
                if strategy_mode == "80/20 Split" and odds >= 5.0:
                    place_stake = stake * 0.8
                    win_stake = stake * 0.2
                    place_odds = ((odds - 1) / 4) + 1
                    p_return, w_return = 0, 0
                    
                    if final_pos == '1':
                        w_return = win_stake * odds
                        p_return = place_stake * place_odds
                        df.at[i, 'Result'] = 'Winner'
                    elif final_pos in ['2', '3', '4']:
                        p_return = place_stake * place_odds
                        df.at[i, 'Result'] = 'Placed'
                    else:
                        df.at[i, 'Result'] = 'Loser'
                    df.at[i, 'P/L'] = round((w_return + p_return) - stake, 2)
                else:
                    if final_pos == '1':
                        df.at[i, 'Result'] = 'Winner'
                        df.at[i, 'P/L'] = round(odds - 1, 2)
                    else:
                        df.at[i, 'Result'] = 'Loser'
                        df.at[i, 'P/L'] = -1.0
                match_count += 1

    if match_count > 0:
        conn.update(spreadsheet=GSHEET_URL, data=df)
        st.sidebar.success(f"✅ Settled {match_count} bets!")
        st.rerun()

# --- 5. SCORING & STAKING ---
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

def calculate_stake(score, base):
    if strategy_mode == "Weighted Score":
        if score >= 30: return base * 1.5
        if score <= 20: return base * 0.5
    return base

def get_best_odds(runner):
    sp_val = runner.get('sp_dec')
    if sp_val and str(sp_val).replace('.','',1).isdigit(): return float(sp_val)
    odds_list = runner.get('odds', [])
    prices = [float(e.get('decimal')) for e in odds_list if str(e.get('decimal')).replace('.','',1).isdigit()]
    return max(prices) if prices else 0.0

# --- 6. PERFORMANCE DASHBOARD (Error-Proofed) ---
st.sidebar.markdown("---")
st.sidebar.header("📊 Stats")

def display_sidebar_stats():
    df = load_ledger()
    if not df.empty:
        # Convert to numeric safely
        df['P/L'] = pd.to_numeric(df['P/L'], errors='coerce').fillna(0)
        df['Stake'] = pd.to_numeric(df['Stake'], errors='coerce').fillna(10)
        df['Market_Move'] = pd.to_numeric(df.get('Market_Move', 0), errors='coerce').fillna(0)
        
        total_profit = (df['P/L'] * df['Stake']).sum()
        roi = (total_profit / df['Stake'].sum()) * 100 if df['Stake'].sum() > 0 else 0
        
        pl_color = "green" if total_profit >= 0 else "red"
        st.sidebar.markdown(f"### Total Profit: :{pl_color}[£{total_profit:,.2f}]")
        st.sidebar.metric("ROI", f"{roi:.1f}%")
        
        avg_clv = df['Market_Move'].mean()
        st.sidebar.metric("Avg Market Move (CLV)", f"{avg_clv:+.2f}")

display_sidebar_stats()

# --- 7. RUN LOGIC ---
st.sidebar.markdown("---")
min_score = st.sidebar.slider("Min Value Score", 0, 50, 20, 5)

if st.button('🚀 Run Analysis'):
    with st.spinner("Analyzing markets..."):
        auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
        r = requests.get("https://api.theracingapi.com/v1/racecards/standard", auth=auth)
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
                            "Odds": odds,
                            "Score": score,
                            "Stake": calculate_stake(score, stake_input),
                            "Result": "Pending",
                            "Pos": "-",
                            "P/L": 0.0,
                            "Market_Move": 0.0
                        })

if st.session_state.value_horses:
    st.markdown(f"### 🏆 Top {strategy_mode} Selections")
    top_3 = sorted(st.session_state.value_horses, key=lambda x: x['Score'], reverse=True)[:3]
    cols = st.columns(3)
    for i, h in enumerate(top_3):
        with cols[i]:
            st.markdown(f"""
            <div style="background-color:#FFD700; padding:20px; border-radius:10px; border:2px solid #DAA520; text-align:center; color:#000;">
                <h2 style="margin:0; color:#000;">{h['Horse']}</h2>
                <p style="margin:5px 0;"><b>{h['Time']} - {h['Course']}</b></p>
                <p style="font-size:22px; margin:5px;"><b>Score: {h['Score']}</b></p>
                <p style="font-size:18px; margin:0;">Stake: £{h['Stake']}</p>
            </div>
            """, unsafe_allow_html=True)

    if st.button("📤 LOG SELECTIONS TO GOOGLE SHEETS"):
        if conn:
            ledger = load_ledger()
            new_df = pd.DataFrame(st.session_state.value_horses)
            filtered = new_df[~new_df['Horse'].isin(ledger['Horse'])]
            if not filtered.empty:
                updated_df = pd.concat([ledger, filtered], ignore_index=True)
                conn.update(spreadsheet=GSHEET_URL, data=updated_df)
                st.balloons()
                st.success(f"Logged {len(filtered)} bets!")
                st.rerun()

if st.session_state.all_races:
    for race in st.session_state.all_races:
        with st.expander(f"🕒 {race.get('off_time', race.get('off'))} - {race.get('course')}"):
            is_aw = "(AW)" in race.get('course', '')
            st.table(pd.DataFrame([{
                "Horse": r.get('horse'),
                "Score": get_score(r, is_aw),
                "Odds": get_best_odds(r),
                "Value": "💎" if (get_score(r, is_aw) >= min_score and get_best_odds(r) >= 5.0) else ""
            } for r in race.get('runners', [])]))

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Auto Reconcile (Live API)"):
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    r = requests.get("https://api.theracingapi.com/v1/results/live", auth=auth)
    if r.status_code == 200:
        process_reconciliation(r.json())
