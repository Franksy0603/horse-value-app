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
    """Loads ledger with defensive checks for every column."""
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            if df is not None:
                # 1. Clean column headers (remove spaces)
                df.columns = [str(c).strip() for c in df.columns]
                
                # 2. Force essential columns to exist so the math doesn't crash
                for col in ["P/L", "Stake", "Result", "Horse", "Course", "Odds"]:
                    if col not in df.columns:
                        df[col] = 0.0 if col in ["P/L", "Stake"] else "-"
                
                # 3. Force numeric types
                df["P/L"] = pd.to_numeric(df["P/L"], errors="coerce").fillna(0.0)
                df["Stake"] = pd.to_numeric(df["Stake"], errors="coerce").fillna(0.0)
                df["Odds"] = pd.to_numeric(df["Odds"], errors="coerce").fillna(1.0)
                return df
        except Exception as e:
            st.error(f"⚠️ Spreadsheet Read Error: {e}")
    return pd.DataFrame()

# --- 3. RECONCILE LOGIC (Enhanced Precision) ---
def clean_txt(text):
    if not text: return ""
    # Remove bracketed text, non-alphanumeric, then uppercase
    text = re.sub(r'\(.*?\)', '', str(text))
    text = re.sub(r'[^A-Za-z0-9\s]', '', text)
    return " ".join(text.split()).upper().strip()

def process_reconciliation(data):
    """Processes results and forces updates even if formatting is off."""
    try:
        results_map = {}
        api_keys_seen = []
        
        for race in data.get('results', []):
            course = clean_txt(race.get('course', ''))
            for runner in race.get('runners', []):
                horse = clean_txt(runner.get('horse', ''))
                pos = str(runner.get('position', ''))
                key = f"{course}|{horse}"
                results_map[key] = pos
                api_keys_seen.append(key)

        df = load_ledger()
        if df.empty: return

        match_count = 0
        mismatch_log = []

        for i, row in df.iterrows():
            # Check for 'Pending' status (case insensitive)
            if str(row.get('Result', '')).strip().upper() in ['PENDING', '-']:
                lookup_key = f"{clean_txt(row.get('Course'))}|{clean_txt(row.get('Horse'))}"
                
                if lookup_key in results_map:
                    final_pos = results_map[lookup_key]
                    df.at[i, 'Pos'] = final_pos
                    if final_pos == '1':
                        df.at[i, 'Result'] = 'Winner'
                        df.at[i, 'P/L'] = float(row.get('Odds', 1)) - 1.0
                    else:
                        df.at[i, 'Result'] = 'Loser'
                        df.at[i, 'P/L'] = -1.0
                    match_count += 1
                else:
                    mismatch_log.append(lookup_key)

        if match_count > 0:
            conn.update(spreadsheet=GSHEET_URL, data=df)
            st.success(f"✅ Successfully settled {match_count} bets!")
            st.rerun()
        else:
            with st.expander("🔍 Reconciliation Diagnostic"):
                st.info("No matches found. Check if names match exactly.")
                st.write("**Your Ledger Keys:**", mismatch_log[:10])
                st.write("**API Result Keys:**", api_keys_seen[:10])

    except Exception as e:
        st.error(f"Reconciliation crashed: {e}")

# --- 4. SIDEBAR DASHBOARD ---
st.sidebar.header("📊 Performance Dashboard")
stake_val = st.sidebar.number_input("Standard Stake (£)", min_value=1, value=10)

def display_sidebar_stats():
    try:
        df = load_ledger()
        if not df.empty:
            # Shielded calculation to prevent crashing on empty/bad rows
            total_profit = (df['P/L'] * df['Stake']).sum()
            total_invested = df['Stake'].sum()
            
            pl_color = "green" if total_profit >= 0 else "red"
            st.sidebar.markdown(f"### Profit: :{pl_color}[£{total_profit:,.2f}]")
            
            c1, c2 = st.sidebar.columns(2)
            c1.metric("Invested", f"£{total_invested:,.0f}")
            roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
            c2.metric("ROI", f"{roi:.1f}%")
            
            st.sidebar.markdown("---")
            st.sidebar.subheader("🔄 Reconcile")
            
            if st.sidebar.button("🔄 Auto-Sync (Standard API)"):
                auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
                all_res = {"results": []}
                for day in [0, 1]:
                    d_str = (datetime.now() - timedelta(days=day)).strftime("%Y-%m-%d")
                    r = requests.get(f"https://api.theracingapi.com/v1/results/standard?date={d_str}", auth=auth)
                    if r.status_code == 200:
                        all_res["results"].extend(r.json().get('results', []))
                process_reconciliation(all_res)
    except Exception as e:
        st.sidebar.error(f"Stats Error: {e}")

display_sidebar_stats()

# --- 5. SCORING ENGINE ---
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

# --- 6. MAIN INTERFACE ---
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
        cols[i].success(f"**{h['Horse']}**\n\n{h['Time']} {h['Course']}\n\nScore: {h['Score']}")
    
    if st.button("📤 Log Selections"):
        ledger = load_ledger()
        new_df = pd.DataFrame(st.session_state.value_horses)
        if not ledger.empty:
            new_df = new_df[~new_df['Horse'].isin(ledger['Horse'])]
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
