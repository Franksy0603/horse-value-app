import streamlit as st
import pandas as pd
import numpy as np
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, date
from streamlit_gsheets import GSheetsConnection

# =========================================================
# VALUE FINDER PRO — SEMI-PRO EDITION
# =========================================================
# Main upgrades vs previous version:
# - Separates raw score from probability, market probability and edge
# - Adds negative scoring factors
# - Adds strategy segmentation: Core Value / Value Longshot / Watchlist
# - Adds market-move support using ledger history or optional live/open odds fields
# - Adds improved ledger schema with implied probability, estimated probability and edge
# - Fixes duplicate prevention to use Date + Horse + Course + Time, not horse name only
# - Adds performance dashboard by score band, odds band, strategy and market move
# - Adds safer API parsing and more transparent diagnostic output

# =========================================================
# 1. SETTINGS
# =========================================================

API_USER = st.secrets.get("API_USER", "")
API_PASS = st.secrets.get("API_PASS", "")
GSHEET_URL = st.secrets.get("gsheet_url", "")
BASE_URL = "https://api.theracingapi.com/v1"

st.set_page_config(page_title="Value Finder Pro — Semi-Pro", layout="wide")
st.title("🏇 Value Finder Pro: Semi-Pro System")
st.caption("Score horses, convert to probability, compare against the market, and track real edge.")

# Keep this intentionally modest. Elite jockeys are obvious to the market and should not dominate scoring.
ELITE_JOCKEYS = [
    "W Buick", "O Murphy", "J Doyle", "R Moore", "T Marquand", "H Doyle",
    "B Curtis", "L Morris", "R L Moore", "William Buick", "Ryan Moore"
]

LEDGER_COLUMNS = [
    "Date", "Horse", "Course", "Time", "Race", "Strategy",
    "Odds_Taken", "SP", "Score", "Score_Band", "Odds_Band",
    "Implied_Prob", "Estimated_Prob", "Edge", "EV",
    "Market_Move", "Market_Move_Band", "Stake", "Bet_Type",
    "Result", "Position", "Return", "P/L", "Reason_Tags", "Notes"
]

# =========================================================
# 2. SIDEBAR CONTROLS
# =========================================================

st.sidebar.header("🛡️ Strategy Settings")
race_filter = st.sidebar.selectbox("Race Type Filter", ["Handicaps Only", "All Race Types"], index=0)
base_stake = st.sidebar.number_input("Base Stake (£)", min_value=1.0, value=5.0, step=1.0)
min_score = st.sidebar.slider("Minimum Raw Score", 0, 80, 30, 5)
min_edge = st.sidebar.slider("Minimum Edge", 0.00, 0.25, 0.05, 0.01)
min_odds = st.sidebar.number_input("Minimum Odds", min_value=1.01, value=5.0, step=0.5)
max_odds = st.sidebar.number_input("Maximum Odds", min_value=1.01, value=40.0, step=1.0)

st.sidebar.divider()
st.sidebar.subheader("📈 Market Filters")
require_steam = st.sidebar.checkbox("Require shortening odds / positive market move", value=False)
allow_longshots_without_steam = st.sidebar.checkbox("Allow 10.0+ longshots without steam", value=True)
strict_strategy_rules = st.sidebar.checkbox(
    "Use strict semi-pro strategy rules",
    value=False,
    help="When off, the sidebar score/edge/odds filters decide qualifiers. When on, selections must also match Core Value / Longshot strategy rules."
)

st.sidebar.divider()
st.sidebar.subheader("💰 Staking")
staking_mode = st.sidebar.selectbox("Staking Mode", ["Flat Stake", "Edge Weighted", "Fractional Kelly Lite"], index=1)
max_stake_multiplier = st.sidebar.slider("Max Stake Multiplier", 1.0, 5.0, 2.0, 0.25)
bet_type_default = st.sidebar.selectbox("Default Bet Type", ["Win", "Each-Way", "Place", "80/20 Win-Place"], index=0)

st.sidebar.divider()
st.sidebar.subheader("👀 Display")
hide_non_qualifiers = st.sidebar.checkbox("Hide Non-Qualifiers", value=True)
show_full_debug = st.sidebar.checkbox("Show Full Runner Debug", value=False)

# =========================================================
# 3. SESSION STATE
# =========================================================

if "value_horses" not in st.session_state:
    st.session_state.value_horses = []
if "all_races" not in st.session_state:
    st.session_state.all_races = []
if "last_run_time" not in st.session_state:
    st.session_state.last_run_time = None

# =========================================================
# 4. GOOGLE SHEETS CONNECTION
# =========================================================

try:
    conn = st.connection("gsheets", type=GSheetsConnection, ttl=0)
except Exception:
    conn = None


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Backwards compatibility with older sheets
    rename_map = {
        "Odds": "Odds_Taken",
        "Place_Odds": "Place_Odds_Old",
        "Pos": "Position",
        "P/L": "P/L",
        "PL": "P/L",
        "Profit/Loss": "P/L",
        "Corse": "Course",
    }
    df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True)

    for col in LEDGER_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    return df[LEDGER_COLUMNS]


def load_ledger() -> pd.DataFrame:
    if conn and GSHEET_URL:
        try:
            df = conn.read(spreadsheet=GSHEET_URL, ttl=0)
            return normalise_columns(df)
        except Exception as e:
            st.warning(f"Could not read Google Sheet. Using empty ledger. Error: {e}")
    return pd.DataFrame(columns=LEDGER_COLUMNS)


def update_ledger(df: pd.DataFrame):
    if not conn or not GSHEET_URL:
        st.error("Google Sheets connection is not configured.")
        return
    conn.update(spreadsheet=GSHEET_URL, data=df[LEDGER_COLUMNS])

# =========================================================
# 5. HELPER FUNCTIONS
# =========================================================


def safe_num(value, default=np.nan):
    try:
        num = pd.to_numeric(value, errors="coerce")
        if pd.isna(num):
            return default
        return float(num)
    except Exception:
        return default


def text_contains(value, needle: str) -> bool:
    return needle.lower() in str(value or "").lower()


def extract_odds(runner: dict) -> tuple[float, str]:
    """Return best currently available decimal odds and source label.

    Important: avoid relying on SP as the main betting price when possible.
    SP is excellent for evaluation, but usually not the price you can select ahead of the race.
    """
    # Prefer live odds array if present
    try:
        odds_list = runner.get("odds") or []
        if isinstance(odds_list, list) and odds_list:
            for item in odds_list:
                dec = safe_num(item.get("decimal"), np.nan)
                if not pd.isna(dec) and dec > 1:
                    bookmaker = item.get("bookmaker") or item.get("bookmaker_name") or "live_odds"
                    return float(dec), str(bookmaker)
    except Exception:
        pass

    # Fallbacks
    for key in ["price", "decimal", "odds_dec", "forecast_dec", "sp_dec"]:
        dec = safe_num(runner.get(key), np.nan)
        if not pd.isna(dec) and dec > 1:
            return float(dec), key

    return 1.0, "missing"


def extract_sp(runner: dict):
    sp = safe_num(runner.get("sp_dec"), np.nan)
    return np.nan if pd.isna(sp) or sp <= 1 else float(sp)


def extract_opening_odds(runner: dict):
    """Best-effort opening/early price extraction.

    The Racing API response shape can vary by plan/add-on. This function safely checks common field names.
    """
    for key in ["opening_odds", "open_odds", "early_price", "forecast_dec", "forecast_odds"]:
        val = safe_num(runner.get(key), np.nan)
        if not pd.isna(val) and val > 1:
            return float(val)

    odds_list = runner.get("odds") or []
    if isinstance(odds_list, list):
        for item in odds_list:
            for key in ["opening_decimal", "opening", "first_decimal", "early_decimal"]:
                val = safe_num(item.get(key), np.nan)
                if not pd.isna(val) and val > 1:
                    return float(val)
    return np.nan


def calculate_market_move(opening_odds, current_odds):
    """Positive means shortening / steam. Negative means drifting."""
    opening = safe_num(opening_odds, np.nan)
    current = safe_num(current_odds, np.nan)
    if pd.isna(opening) or pd.isna(current) or opening <= 1 or current <= 1:
        return np.nan
    return round(opening - current, 2)


def get_days_since_last_run(runner: dict):
    for key in ["days_since_last_run", "dslr", "days_off", "last_run_days"]:
        val = safe_num(runner.get(key), np.nan)
        if not pd.isna(val):
            return int(val)
    return np.nan


def score_band(score: float) -> str:
    if score < 25:
        return "<25"
    if score < 30:
        return "25-29"
    if score < 35:
        return "30-34"
    if score < 45:
        return "35-44"
    return "45+"


def odds_band(odds: float) -> str:
    if odds < 5:
        return "<5"
    if odds < 8:
        return "5-7.99"
    if odds < 12:
        return "8-11.99"
    if odds < 20:
        return "12-19.99"
    return "20+"


def market_move_band(move) -> str:
    if pd.isna(move):
        return "Unknown"
    if move >= 2:
        return "Strong Steam"
    if move > 0:
        return "Steam"
    if move == 0:
        return "Flat"
    if move > -2:
        return "Drift"
    return "Strong Drift"

# =========================================================
# 6. SCORING ENGINE
# =========================================================


def get_advanced_score(runner: dict, race: dict) -> tuple[int, list[str], bool]:
    score = 0
    reasons = []

    # Recent form
    form = str(runner.get("form", "") or "").replace("-", "").replace("/", "")
    if form.endswith("1"):
        score += 12
        reasons.append("LTO Winner")
    elif len(form) >= 2 and form[-1] in ["2", "3"]:
        score += 6
        reasons.append("Recent Placed Form")
    elif len(form) >= 2 and form[-1] in ["0", "8", "9"]:
        score -= 6
        reasons.append("Poor LTO")

    # Class movement: UK class numbers: Class 1 is highest, Class 6 is lowest.
    curr_class = safe_num(race.get("class"), np.nan)
    last_class = safe_num(runner.get("last_class"), np.nan)
    if not pd.isna(curr_class) and not pd.isna(last_class):
        if curr_class > last_class:
            score += 10
            reasons.append("Class Drop")
        elif curr_class < last_class:
            score -= 6
            reasons.append("Class Rise")

    # Trainer 14-day form
    t_stats = runner.get("trainer_14_days", {})
    if isinstance(t_stats, dict):
        win_pc = safe_num(t_stats.get("percent"), 0)
        runs = safe_num(t_stats.get("runs"), np.nan)
        if win_pc >= 25 and (pd.isna(runs) or runs >= 5):
            score += 12
            reasons.append("Trainer Hot")
        elif win_pc >= 15:
            score += 6
            reasons.append("Trainer OK")
        elif win_pc == 0 and not pd.isna(runs) and runs >= 8:
            score -= 8
            reasons.append("Trainer Cold")

    # Jockey: small boost only, because the market prices this in heavily.
    jockey = str(runner.get("jockey", "") or "")
    is_elite = any(elite.lower() in jockey.lower() for elite in ELITE_JOCKEYS)
    if is_elite:
        score += 4
        reasons.append("Elite Jockey")

    # Course and distance
    cd_flag = str(runner.get("cd", "") or "").upper()
    if "CD" in cd_flag:
        score += 8
        reasons.append("Course & Distance")
    elif "C" in cd_flag:
        score += 4
        reasons.append("Course Winner")
    elif "D" in cd_flag:
        score += 4
        reasons.append("Distance Winner")

    # Headgear: smaller boost; this is noisy.
    headgear = str(runner.get("headgear", "") or "").lower()
    if "1" in headgear:
        score += 4
        reasons.append("1st Headgear")

    # Days since last run
    dslr = get_days_since_last_run(runner)
    if not pd.isna(dslr):
        if 7 <= dslr <= 35:
            score += 8
            reasons.append("Good Recency")
        elif dslr > 90:
            score -= 10
            reasons.append("Long Layoff")
        elif dslr < 5:
            score -= 4
            reasons.append("Quick Turnaround")

    # Weight / OR / age placeholders: safe if fields exist.
    age = safe_num(runner.get("age"), np.nan)
    if not pd.isna(age):
        if age >= 10:
            score -= 5
            reasons.append("Older Horse")

    # Keep score in sensible range
    score = int(max(0, min(score, 80)))
    return score, reasons, is_elite


def estimate_probability(score: float, odds: float, market_move=np.nan) -> float:
    """Simple calibrated heuristic probability.

    This is not a true trained model yet. It is deliberately conservative and anchored to the market,
    because racing markets are strong. Your score can move the horse above or below market probability.
    """
    if odds <= 1:
        return 0.0

    market_prob = 1 / odds

    # Score adjustment: score 30 is roughly neutral, higher scores increase estimated chance.
    score_adjustment = (score - 30) * 0.004

    # Market steam adjustment: positive move implies shortening.
    move_adjustment = 0
    if not pd.isna(market_move):
        move_adjustment = np.clip(market_move * 0.01, -0.04, 0.04)

    estimated = market_prob + score_adjustment + move_adjustment

    # Conservative caps: avoid fantasy probabilities on longshots.
    if odds >= 20:
        estimated = min(estimated, 0.12)
    elif odds >= 12:
        estimated = min(estimated, 0.18)
    elif odds >= 8:
        estimated = min(estimated, 0.24)
    else:
        estimated = min(estimated, 0.35)

    return round(float(max(0.01, estimated)), 4)


def calculate_edge(estimated_prob: float, odds: float) -> tuple[float, float]:
    implied = 1 / odds if odds > 1 else 1
    edge = estimated_prob - implied
    ev = (estimated_prob * odds) - 1
    return round(edge, 4), round(ev, 4)


def assign_strategy(score, odds, edge, market_move) -> str:
    """Label the runner type.

    This function should describe the selection, not silently block it.
    The actual yes/no decision happens in qualifies_selection().
    """
    has_steam = not pd.isna(market_move) and market_move > 0

    if odds >= 10:
        return "Value Longshot + Steam" if has_steam else "Value Longshot"

    if 5 <= odds < 10:
        return "Core Value" if has_steam else "Core Value - No Steam"

    if odds < 5:
        return "Short Price Watchlist"

    return "Watchlist Value"


def calculate_stake(base, odds, estimated_prob, edge):
    if staking_mode == "Flat Stake":
        return round(base, 2)

    if staking_mode == "Edge Weighted":
        multiplier = 1 + max(0, edge * 10)
        multiplier = min(multiplier, max_stake_multiplier)
        return round(base * multiplier, 2)

    # Fractional Kelly Lite; capped and deliberately conservative.
    b = odds - 1
    p = estimated_prob
    q = 1 - p
    kelly = ((b * p) - q) / b if b > 0 else 0
    fractional = max(0, kelly * 0.25)
    multiplier = min(max_stake_multiplier, max(0.5, fractional * 10))
    return round(base * multiplier, 2)


def qualifies_selection(strategy, odds, score, edge, market_move):
    """Final qualifier gate.

    Important fix: the previous version hard-coded strategy requirements of score >= 30.
    That meant the sidebar sliders could be set to 0 and still return no qualifiers.
    This version respects your sidebar settings first, then optionally applies stricter strategy rules.
    """
    if odds < min_odds or odds > max_odds:
        return False
    if score < min_score:
        return False
    if edge < min_edge:
        return False

    has_steam = not pd.isna(market_move) and market_move > 0

    if require_steam:
        if has_steam:
            return True
        if allow_longshots_without_steam and odds >= 10:
            return True
        return False

    if strict_strategy_rules:
        if odds >= 10 and score >= 30:
            return True
        if 5 <= odds < 10 and score >= 30 and has_steam:
            return True
        if score >= 35 and edge >= min_edge:
            return True
        return False

    return True

# =========================================================
# 7. API FETCHING
# =========================================================


def fetch_racecards():
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    response = requests.get(f"{BASE_URL}/racecards/standard", auth=auth, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("racecards", [])


def analyse_racecards(racecards):
    selections = []

    for race in racecards:
        race_name = str(race.get("race_name", "") or "")
        is_hcap = "handicap" in race_name.lower()
        if race_filter == "Handicaps Only" and not is_hcap:
            continue

        for runner in race.get("runners", []) or []:
            odds, odds_source = extract_odds(runner)
            if odds <= 1:
                continue

            opening_odds = extract_opening_odds(runner)
            market_move = calculate_market_move(opening_odds, odds)

            score, reasons, is_elite = get_advanced_score(runner, race)
            implied_prob = round(1 / odds, 4)
            estimated_prob = estimate_probability(score, odds, market_move)
            edge, ev = calculate_edge(estimated_prob, odds)
            strategy = assign_strategy(score, odds, edge, market_move)
            stake = calculate_stake(base_stake, odds, estimated_prob, edge)

            selection = {
                "Date": datetime.now().strftime("%Y-%m-%d"),
                "Horse": runner.get("horse"),
                "Course": race.get("course"),
                "Time": race.get("off_time", "N/A"),
                "Race": race_name,
                "Strategy": strategy,
                "Odds_Taken": odds,
                "Odds_Source": odds_source,
                "Opening_Odds": opening_odds,
                "SP": extract_sp(runner),
                "Score": score,
                "Score_Band": score_band(score),
                "Odds_Band": odds_band(odds),
                "Implied_Prob": implied_prob,
                "Estimated_Prob": estimated_prob,
                "Edge": edge,
                "EV": ev,
                "Market_Move": market_move,
                "Market_Move_Band": market_move_band(market_move),
                "Stake": stake,
                "Bet_Type": bet_type_default,
                "Result": "Pending",
                "Position": np.nan,
                "Return": 0.0,
                "P/L": 0.0,
                "Reason_Tags": " | ".join(reasons),
                "Notes": f"Odds source: {odds_source}",
                "Elite": is_elite,
                "Qualifies": qualifies_selection(strategy, odds, score, edge, market_move),
            }
            selections.append(selection)

    return selections

# =========================================================
# 8. PERFORMANCE ANALYSIS
# =========================================================


def prepare_numeric_ledger(df: pd.DataFrame) -> pd.DataFrame:
    df = normalise_columns(df)
    numeric_cols = ["Odds_Taken", "SP", "Score", "Implied_Prob", "Estimated_Prob", "Edge", "EV", "Market_Move", "Stake", "Return", "P/L"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def performance_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    df = prepare_numeric_ledger(df)
    settled = df[df["Result"].astype(str).str.lower().ne("pending")].copy()
    if settled.empty or group_col not in settled.columns:
        return pd.DataFrame()

    grouped = settled.groupby(group_col, dropna=False).agg(
        Bets=("Horse", "count"),
        Staked=("Stake", "sum"),
        Return=("Return", "sum"),
        PL=("P/L", "sum"),
        Avg_Odds=("Odds_Taken", "mean"),
        Avg_Edge=("Edge", "mean"),
    ).reset_index()
    grouped["ROI"] = np.where(grouped["Staked"] > 0, grouped["PL"] / grouped["Staked"], np.nan)
    grouped["ROI"] = grouped["ROI"].round(3)
    grouped["Avg_Odds"] = grouped["Avg_Odds"].round(2)
    grouped["Avg_Edge"] = grouped["Avg_Edge"].round(3)
    grouped["PL"] = grouped["PL"].round(2)
    grouped["Staked"] = grouped["Staked"].round(2)
    grouped["Return"] = grouped["Return"].round(2)
    return grouped.sort_values("PL", ascending=False)

# =========================================================
# 9. UI TABS
# =========================================================

tab1, tab2, tab3, tab4 = st.tabs([
    "🚀 Market Analysis", "📊 Ledger", "📈 Performance", "🧪 Debug / API Fields"
])

with tab1:
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        run_button = st.button("🚀 Run Analysis", use_container_width=True)
    with c2:
        clear_button = st.button("🧹 Clear Results", use_container_width=True)

    if clear_button:
        st.session_state.value_horses = []
        st.session_state.all_races = []
        st.session_state.last_run_time = None
        st.success("Cleared current analysis.")

    if run_button:
        with st.spinner("Fetching and processing racecards..."):
            try:
                racecards = fetch_racecards()
                st.session_state.all_races = racecards
                analysed = analyse_racecards(racecards)
                st.session_state.value_horses = analysed
                st.session_state.last_run_time = datetime.now().strftime("%H:%M:%S")
                qualifiers = [x for x in analysed if x["Qualifies"]]
                st.success(f"Analysis complete. {len(qualifiers)} qualifiers from {len(analysed)} analysed runners.")
            except requests.HTTPError as e:
                st.error(f"API request failed: {e}")
            except Exception as e:
                st.error(f"Analysis failed: {e}")

    if st.session_state.last_run_time:
        st.caption(f"Last run: {st.session_state.last_run_time}")

    if st.session_state.value_horses:
        df_all = pd.DataFrame(st.session_state.value_horses)
        df_show = df_all[df_all["Qualifies"]].copy() if hide_non_qualifiers else df_all.copy()
        df_show = df_show.sort_values(["Qualifies", "EV", "Score"], ascending=[False, False, False])

        st.divider()
        q_count = int(df_all["Qualifies"].sum())
        total_count = len(df_all)
        avg_edge = df_all.loc[df_all["Qualifies"], "Edge"].mean() if q_count else 0
        m1, m2, m3 = st.columns(3)
        m1.metric("Qualifiers", q_count)
        m2.metric("Analysed Runners", total_count)
        m3.metric("Avg Qualifier Edge", f"{avg_edge:.2%}" if q_count else "0.00%")

        st.subheader("🎯 Qualified Selections")
        if df_show.empty:
            st.info("No qualifiers match the current settings.")
        else:
            card_cols = st.columns(3)
            for idx, (_, h) in enumerate(df_show.head(18).iterrows()):
                with card_cols[idx % 3]:
                    border = "4px solid #111" if bool(h.get("Elite")) and h["Score"] >= 35 else "1px solid #333"
                    bg = "#F7F4E8" if h["Qualifies"] else "#F1F1F1"
                    st.markdown(
                        f"""
                        <div style="background:{bg}; padding:14px; border-radius:12px; color:#000; border:{border}; min-height:245px; margin-bottom:12px;">
                            <h3 style="margin:0 0 4px 0;">{h['Horse']}</h3>
                            <b>{h['Time']} - {h['Course']}</b><br>
                            <small>{h['Race']}</small>
                            <hr style="margin:8px 0;">
                            <b>{h['Strategy']}</b><br>
                            Odds: <b>{h['Odds_Taken']:.2f}</b> | Score: <b>{int(h['Score'])}</b><br>
                            Est Prob: <b>{h['Estimated_Prob']:.1%}</b> | Market: <b>{h['Implied_Prob']:.1%}</b><br>
                            Edge: <b>{h['Edge']:.1%}</b> | EV: <b>{h['EV']:.2f}</b><br>
                            Market: {h['Market_Move_Band']} ({h['Market_Move'] if not pd.isna(h['Market_Move']) else 'n/a'})<br>
                            Stake: <b>£{h['Stake']:.2f}</b><br>
                            <small>{h['Reason_Tags']}</small>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            st.subheader("Selection Table")
            display_cols = [
                "Qualifies", "Horse", "Course", "Time", "Strategy", "Odds_Taken", "Opening_Odds",
                "Market_Move", "Score", "Implied_Prob", "Estimated_Prob", "Edge", "EV", "Stake", "Reason_Tags"
            ]
            st.dataframe(df_show[display_cols], use_container_width=True)

            if st.button("📤 Log Qualifiers to Ledger", use_container_width=True):
                ledger = load_ledger()
                qualifiers = df_all[df_all["Qualifies"]].copy()

                if qualifiers.empty:
                    st.warning("No qualifying selections to log.")
                else:
                    rows = []
                    for _, h in qualifiers.iterrows():
                        rows.append({col: h.get(col, np.nan) for col in LEDGER_COLUMNS})
                    new_df = pd.DataFrame(rows)
                    new_df = normalise_columns(new_df)

                    # Robust duplicate key: date + horse + course + time
                    ledger_key = (
                        ledger["Date"].astype(str) + "|" + ledger["Horse"].astype(str) + "|" +
                        ledger["Course"].astype(str) + "|" + ledger["Time"].astype(str)
                    ) if not ledger.empty else pd.Series(dtype=str)
                    new_key = (
                        new_df["Date"].astype(str) + "|" + new_df["Horse"].astype(str) + "|" +
                        new_df["Course"].astype(str) + "|" + new_df["Time"].astype(str)
                    )

                    to_add = new_df[~new_key.isin(set(ledger_key))]
                    updated = pd.concat([ledger, to_add], ignore_index=True)
                    update_ledger(updated)
                    st.success(f"Logged {len(to_add)} new selections. Skipped {len(new_df) - len(to_add)} duplicates.")
                    st.balloons()

        st.divider()
        st.subheader("🏁 Full Race Details")
        for race in st.session_state.all_races:
            race_name = str(race.get("race_name", "") or "")
            is_hcap = "handicap" in race_name.lower()
            if race_filter == "Handicaps Only" and not is_hcap:
                continue

            runners = df_all[(df_all["Course"] == race.get("course")) & (df_all["Time"] == race.get("off_time", "N/A"))]
            if hide_non_qualifiers and not runners["Qualifies"].any():
                continue

            with st.expander(f"🕒 {race.get('off_time')} - {race.get('course')} — {race_name}"):
                cols = ["Qualifies", "Horse", "Odds_Taken", "Score", "Estimated_Prob", "Edge", "EV", "Strategy", "Reason_Tags"]
                st.dataframe(runners[cols].sort_values("EV", ascending=False), use_container_width=True)

with tab2:
    st.subheader("Performance Ledger")
    ledger = load_ledger()
    st.dataframe(ledger, use_container_width=True)
    st.caption("Update results, positions, returns and P/L in your Google Sheet, then refresh this tab.")

with tab3:
    st.subheader("📈 Performance Dashboard")
    ledger = load_ledger()
    ledger = prepare_numeric_ledger(ledger)

    settled = ledger[ledger["Result"].astype(str).str.lower().ne("pending")].copy()
    if settled.empty:
        st.info("No settled bets found yet. Mark results in your ledger to unlock performance analysis.")
    else:
        total_bets = len(settled)
        total_staked = settled["Stake"].sum()
        total_pl = settled["P/L"].sum()
        roi = total_pl / total_staked if total_staked else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Settled Bets", total_bets)
        c2.metric("Total Staked", f"£{total_staked:.2f}")
        c3.metric("P/L", f"£{total_pl:.2f}")
        c4.metric("ROI", f"{roi:.1%}")

        for group in ["Strategy", "Score_Band", "Odds_Band", "Market_Move_Band", "Bet_Type", "Course"]:
            st.markdown(f"### ROI by {group}")
            summary = performance_summary(ledger, group)
            if summary.empty:
                st.info(f"No data available for {group}.")
            else:
                st.dataframe(summary, use_container_width=True)

with tab4:
    st.subheader("🧪 Debug / API Fields")
    st.write("Use this to inspect exactly what your current API tier returns. This is important before adding more features.")

    if not st.session_state.all_races:
        st.info("Run analysis first to inspect API fields.")
    else:
        first_race = st.session_state.all_races[0]
        st.markdown("### First Race Object")
        st.json(first_race)

        runners = first_race.get("runners", []) or []
        if runners:
            st.markdown("### First Runner Object")
            st.json(runners[0])

        if show_full_debug:
            st.markdown("### Analysed Runner Data")
            st.dataframe(pd.DataFrame(st.session_state.value_horses), use_container_width=True)
