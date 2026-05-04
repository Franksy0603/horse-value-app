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
min_score = st.sidebar.slider(
    "Minimum Raw Score",
    0,
    80,
    25,
    5,
    help="Start around 20–25 while the model is being calibrated. Increase only after you have enough settled results."
)
min_edge = st.sidebar.slider(
    "Minimum Edge",
    -0.50,
    0.25,
    -0.05,
    0.01,
    help="0.00 means only horses with non-negative estimated edge qualify. Use a negative value when testing or calibrating the model."
)
min_odds = st.sidebar.number_input("Minimum Odds", min_value=1.01, value=5.0, step=0.5)
max_odds = st.sidebar.number_input("Maximum Odds", min_value=1.01, value=40.0, step=1.0)

st.sidebar.divider()
st.sidebar.subheader("📈 Market Filters")
require_steam = st.sidebar.checkbox("Require shortening odds / positive market move", value=False)
allow_longshots_without_steam = st.sidebar.checkbox("Allow 10.0+ longshots without steam", value=True)
qualification_mode = st.sidebar.selectbox(
    "Qualification Mode",
    ["Testing: show anything passing odds", "Score + Edge", "Strict Semi-Pro"],
    index=1,
    help="Use Testing mode first to confirm runners display. Then move to Score + Edge or Strict Semi-Pro once the data is flowing."
)
strict_strategy_rules = qualification_mode == "Strict Semi-Pro"

st.sidebar.divider()
st.sidebar.subheader("🧠 Auto-Calibration")
use_auto_calibration = st.sidebar.checkbox(
    "Use ledger-based calibration",
    value=True,
    help="Uses your settled ledger results to adjust estimated probabilities by score band and odds band. Falls back to heuristic estimates when sample size is too small."
)
min_calibration_samples = st.sidebar.slider(
    "Min samples per calibration bucket",
    5,
    100,
    20,
    5,
    help="Lower values react faster but are noisier. Use 20+ once you have enough results."
)
calibration_blend = st.sidebar.slider(
    "Calibration strength",
    0.0,
    1.0,
    0.50,
    0.05,
    help="0 = heuristic only. 1 = calibration only. 0.5 is a sensible starting point."
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
show_filter_diagnostics = st.sidebar.checkbox("Show filter diagnostics", value=True)

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
        return False
    conn.update(spreadsheet=GSHEET_URL, data=df[LEDGER_COLUMNS])
    return True


def make_selection_key(df: pd.DataFrame) -> pd.Series:
    """Stable key for avoiding duplicates and reconciling results."""
    if df is None or df.empty:
        return pd.Series(dtype=str)
    return (
        df["Date"].astype(str).str.strip() + "|" +
        df["Horse"].astype(str).str.strip() + "|" +
        df["Course"].astype(str).str.strip() + "|" +
        df["Time"].astype(str).str.strip()
    )


def calculate_return_and_pl(result: str, odds_taken, stake, manual_return=None):
    """Calculate return and P/L for simple win-style settlement.

    For Each-Way / Place / 80-20 bets, use the manual return override for accuracy.
    """
    stake = safe_num(stake, 0)
    odds_taken = safe_num(odds_taken, np.nan)

    if manual_return not in [None, ""]:
        ret = safe_num(manual_return, 0)
        return round(ret, 2), round(ret - stake, 2)

    result_clean = str(result or "").strip().lower()
    if result_clean in ["win", "won", "winner"] and not pd.isna(odds_taken):
        ret = stake * odds_taken
    elif result_clean in ["void", "non-runner", "nr"]:
        ret = stake
    else:
        ret = 0.0

    return round(ret, 2), round(ret - stake, 2)

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
# 6. AUTO-CALIBRATION ENGINE
# =========================================================

def is_win_result(value) -> bool:
    txt = str(value or "").strip().lower()
    return txt in ["win", "won", "winner", "1", "1st"]


def build_calibration_tables(ledger: pd.DataFrame):
    """Build empirical win-rate tables from settled ledger results.

    Priority order during prediction:
    1. Score band + odds band
    2. Score band only
    3. Odds band only
    4. Overall ledger win rate

    Each table includes sample size, win rate and average odds so the app can avoid trusting tiny buckets too much.
    """
    ledger = prepare_numeric_ledger(ledger)
    if ledger.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None

    settled = ledger[ledger["Result"].astype(str).str.lower().ne("pending")].copy()
    settled = settled.dropna(subset=["Score", "Odds_Taken"])

    if settled.empty:
        return {}, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None

    settled["Win_Flag"] = settled["Result"].apply(is_win_result).astype(int)
    settled["Score_Band"] = settled["Score"].apply(score_band)
    settled["Odds_Band"] = settled["Odds_Taken"].apply(odds_band)

    overall = {
        "samples": int(len(settled)),
        "win_rate": float(settled["Win_Flag"].mean()),
        "avg_odds": float(settled["Odds_Taken"].mean()),
    }

    combo = settled.groupby(["Score_Band", "Odds_Band"]).agg(
        Samples=("Win_Flag", "count"),
        Wins=("Win_Flag", "sum"),
        Win_Rate=("Win_Flag", "mean"),
        Avg_Odds=("Odds_Taken", "mean"),
        PL=("P/L", "sum"),
        Staked=("Stake", "sum"),
    ).reset_index()

    score_tbl = settled.groupby("Score_Band").agg(
        Samples=("Win_Flag", "count"),
        Wins=("Win_Flag", "sum"),
        Win_Rate=("Win_Flag", "mean"),
        Avg_Odds=("Odds_Taken", "mean"),
        PL=("P/L", "sum"),
        Staked=("Stake", "sum"),
    ).reset_index()

    odds_tbl = settled.groupby("Odds_Band").agg(
        Samples=("Win_Flag", "count"),
        Wins=("Win_Flag", "sum"),
        Win_Rate=("Win_Flag", "mean"),
        Avg_Odds=("Odds_Taken", "mean"),
        PL=("P/L", "sum"),
        Staked=("Stake", "sum"),
    ).reset_index()

    for table in [combo, score_tbl, odds_tbl]:
        if not table.empty:
            table["ROI"] = np.where(table["Staked"] > 0, table["PL"] / table["Staked"], np.nan)
            table["Win_Rate"] = table["Win_Rate"].round(4)
            table["Avg_Odds"] = table["Avg_Odds"].round(2)
            table["ROI"] = table["ROI"].round(3)

    return {}, combo, score_tbl, odds_tbl, overall


def lookup_calibrated_probability(score, odds, heuristic_prob, combo_tbl, score_tbl, odds_tbl, overall):
    """Blend heuristic probability with empirical ledger probability.

    Uses simple Bayesian smoothing so tiny samples do not create extreme probabilities.
    """
    if not use_auto_calibration or overall is None:
        return heuristic_prob, "Heuristic only"

    sb = score_band(score)
    ob = odds_band(odds)

    candidates = []

    if combo_tbl is not None and not combo_tbl.empty:
        row = combo_tbl[(combo_tbl["Score_Band"] == sb) & (combo_tbl["Odds_Band"] == ob)]
        if not row.empty:
            r = row.iloc[0]
            candidates.append(("Score+Odds bucket", int(r["Samples"]), float(r["Win_Rate"])))

    if score_tbl is not None and not score_tbl.empty:
        row = score_tbl[score_tbl["Score_Band"] == sb]
        if not row.empty:
            r = row.iloc[0]
            candidates.append(("Score bucket", int(r["Samples"]), float(r["Win_Rate"])))

    if odds_tbl is not None and not odds_tbl.empty:
        row = odds_tbl[odds_tbl["Odds_Band"] == ob]
        if not row.empty:
            r = row.iloc[0]
            candidates.append(("Odds bucket", int(r["Samples"]), float(r["Win_Rate"])))

    candidates.append(("Overall ledger", int(overall["samples"]), float(overall["win_rate"])))

    chosen_label, samples, raw_rate = candidates[-1]
    for label, n, rate in candidates:
        if n >= min_calibration_samples:
            chosen_label, samples, raw_rate = label, n, rate
            break

    # Bayesian smoothing toward market/heuristic to avoid overreacting.
    prior_strength = max(10, min_calibration_samples)
    smoothed_rate = ((raw_rate * samples) + (heuristic_prob * prior_strength)) / (samples + prior_strength)

    # Blend with heuristic. This lets calibration improve the model gradually.
    calibrated = (heuristic_prob * (1 - calibration_blend)) + (smoothed_rate * calibration_blend)

    # Safety cap/floor.
    calibrated = min(max(calibrated, 0.005), 0.50)
    source = f"{chosen_label} ({samples} samples, raw {raw_rate:.1%})"
    return round(float(calibrated), 4), source

# =========================================================
# 7. SCORING ENGINE
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

    # Signal stacking: reward stronger combinations rather than treating every signal as isolated.
    reason_set = set(reasons)
    if "LTO Winner" in reason_set and "Class Drop" in reason_set:
        score += 8
        reasons.append("Power Combo: LTO + Class Drop")

    if "Trainer Hot" in reason_set and ("Course & Distance" in reason_set or "Course Winner" in reason_set):
        score += 6
        reasons.append("Power Combo: Hot Trainer + Track Fit")

    if "Good Recency" in reason_set and ("Recent Placed Form" in reason_set or "LTO Winner" in reason_set):
        score += 5
        reasons.append("Power Combo: Fit + In Form")

    if "Long Layoff" in reason_set and "Trainer Cold" in reason_set:
        score -= 8
        reasons.append("Risk Combo: Layoff + Cold Trainer")

    # Keep score in sensible range
    score = int(max(0, min(score, 100)))
    return score, reasons, is_elite


def estimate_probability(score: float, odds: float, market_move=np.nan) -> float:
    """Semi-pro heuristic probability estimate.

    This is still not a trained model, but it is better calibrated for your current system:
    - It anchors to market probability because markets are strong.
    - Score 25 is treated as roughly neutral.
    - Stronger scores are allowed to create real overlays.
    - Probability caps are loosened so longshots are not killed automatically.
    """
    if odds <= 1:
        return 0.0

    market_prob = 1 / odds

    # Stronger score impact than the earlier conservative version.
    # Score 25 = neutral. Every 5 points above/below moves probability by about 4 percentage points.
    score_adjustment = (score - 25) * 0.008

    # Market steam adjustment: positive means odds have shortened.
    move_adjustment = 0
    if not pd.isna(market_move):
        move_adjustment = np.clip(market_move * 0.0125, -0.06, 0.06)

    estimated = market_prob + score_adjustment + move_adjustment

    # Softer universal cap. This prevents impossible probabilities without suppressing longshot edge.
    estimated = min(estimated, 0.50)

    return round(float(max(0.005, estimated)), 4)


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

    Testing mode deliberately ignores score and edge so you can confirm that API runners
    and odds are being displayed before tightening the model filters.
    """
    if odds < min_odds or odds > max_odds:
        return False

    has_steam = not pd.isna(market_move) and market_move > 0

    if require_steam:
        if not has_steam and not (allow_longshots_without_steam and odds >= 10):
            return False

    if qualification_mode == "Testing: show anything passing odds":
        return True

    if score < min_score:
        return False
    if pd.isna(edge) or edge < min_edge:
        return False

    if qualification_mode == "Score + Edge":
        return True

    # Strict Semi-Pro
    if odds >= 10 and score >= 25:
        return True
    if 5 <= odds < 10 and score >= 25 and has_steam:
        return True
    if score >= 30 and edge >= min_edge:
        return True
    return False

# =========================================================
# 8. API FETCHING
# =========================================================


def fetch_racecards():
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    response = requests.get(f"{BASE_URL}/racecards/standard", auth=auth, timeout=30)
    response.raise_for_status()
    data = response.json()
    return data.get("racecards", [])


def fetch_results_for_date(target_date: str):
    """Fetch racing results for a date from The Racing API.

    The /v1/results endpoint expects start_date, end_date, limit and skip.
    It returns paginated results, so this function fetches all available pages for the selected date.
    """
    auth = HTTPBasicAuth(API_USER.strip(), API_PASS.strip())
    url = f"{BASE_URL}/results"
    limit = 50
    skip = 0
    all_results = []
    errors = []

    while True:
        params = {
            "start_date": target_date,
            "end_date": target_date,
            "limit": limit,
            "skip": skip,
        }

        try:
            response = requests.get(url, auth=auth, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            races = extract_result_races(data)
            if races:
                all_results.extend(races)

            total = safe_num(data.get("total", 0), 0) if isinstance(data, dict) else len(all_results)
            skip += limit

            if skip >= total or not races:
                break

        except Exception as e:
            errors.append(str(e))
            break

    if all_results:
        return all_results, f"{url}?start_date={target_date}&end_date={target_date}"

    # Fallback for accounts/plans where results may also be embedded in standard racecards.
    fallback_requests = [
        (f"{BASE_URL}/racecards/standard", {"start_date": target_date, "end_date": target_date, "limit": limit, "skip": 0}),
    ]

    for fb_url, params in fallback_requests:
        try:
            response = requests.get(fb_url, auth=auth, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            races = extract_result_races(data)
            if races:
                return races, f"{fb_url}?start_date={target_date}&end_date={target_date}"
        except Exception as e:
            errors.append(f"{fb_url}: {e}")

    return [], " | ".join(errors)


def normalise_name(value):
    txt = str(value or "").lower().strip()
    keep = []
    for ch in txt:
        if ch.isalnum() or ch.isspace():
            keep.append(ch)
    return " ".join("".join(keep).split())


def normalise_time(value):
    txt = str(value or "").strip()
    if not txt:
        return ""
    # Handles '14:30', '2:30', '14:30:00'
    try:
        return pd.to_datetime(txt).strftime("%H:%M")
    except Exception:
        return txt[:5]


def extract_result_races(data):
    """Return a list of race dictionaries from common API response shapes."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    for key in ["results", "racecards", "races", "data"]:
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_result_races(value)
            if nested:
                return nested
    return []


def extract_result_runners(race):
    for key in ["runners", "results", "finishers", "horses"]:
        value = race.get(key) if isinstance(race, dict) else None
        if isinstance(value, list):
            return value
    return []


def extract_position(runner):
    for key in ["position", "pos", "finish_position", "finishing_position", "result"]:
        val = runner.get(key) if isinstance(runner, dict) else None
        if val not in [None, ""]:
            txt = str(val).strip().lower()
            if txt in ["nr", "non-runner", "non runner"]:
                return "NR"
            digits = "".join(ch for ch in txt if ch.isdigit())
            if digits:
                return int(digits)
    return np.nan


def extract_runner_sp_from_result(runner):
    for key in ["sp_dec", "sp", "bsp", "starting_price", "starting_price_dec"]:
        val = safe_num(runner.get(key), np.nan) if isinstance(runner, dict) else np.nan
        if not pd.isna(val) and val > 1:
            return float(val)
    return np.nan


def race_matches_ledger_row(race, row):
    race_course = normalise_name(race.get("course") or race.get("track") or race.get("course_name"))
    row_course = normalise_name(row.get("Course"))
    if race_course and row_course and race_course != row_course:
        return False

    race_time = normalise_time(race.get("off_time") or race.get("time") or race.get("race_time"))
    row_time = normalise_time(row.get("Time"))
    if race_time and row_time and race_time != row_time:
        return False

    return True


def find_result_for_ledger_row(row, result_races):
    target_horse = normalise_name(row.get("Horse"))
    if not target_horse:
        return None, "Missing horse name"

    possible_races = [race for race in result_races if isinstance(race, dict) and race_matches_ledger_row(race, row)]
    if not possible_races:
        return None, "No matching race"

    for race in possible_races:
        runners = extract_result_runners(race)
        for runner in runners:
            horse_name = normalise_name(runner.get("horse") or runner.get("horse_name") or runner.get("name"))
            if horse_name == target_horse:
                return {"race": race, "runner": runner}, "Matched"

    # Fuzzy-ish fallback: exact words contained either way.
    for race in possible_races:
        runners = extract_result_runners(race)
        for runner in runners:
            horse_name = normalise_name(runner.get("horse") or runner.get("horse_name") or runner.get("name"))
            if horse_name and (horse_name in target_horse or target_horse in horse_name):
                return {"race": race, "runner": runner}, "Fuzzy matched"

    return None, "Race found, horse not matched"


def result_label_from_position(position):
    if str(position).upper() == "NR":
        return "Non-Runner"
    pos = safe_num(position, np.nan)
    if pd.isna(pos):
        return "Pending"
    if int(pos) == 1:
        return "Win"
    return "Lose"


def auto_reconcile_pending_results(target_date: str):
    ledger = load_ledger()
    if ledger.empty:
        return ledger, pd.DataFrame(), "Ledger is empty"

    pending_mask = (
        ledger["Result"].astype(str).str.lower().eq("pending") &
        ledger["Date"].astype(str).eq(target_date)
    )
    pending = ledger[pending_mask].copy()
    if pending.empty:
        return ledger, pd.DataFrame(), "No pending selections for this date"

    result_races, source = fetch_results_for_date(target_date)
    if not result_races:
        return ledger, pd.DataFrame(), f"No results returned. Tried: {source}"

    audit_rows = []
    for idx, row in pending.iterrows():
        match, status = find_result_for_ledger_row(row, result_races)
        if not match:
            audit_rows.append({
                "Horse": row.get("Horse"), "Course": row.get("Course"), "Time": row.get("Time"),
                "Status": status, "Updated": False
            })
            continue

        runner = match["runner"]
        position = extract_position(runner)
        result_label = result_label_from_position(position)
        sp = extract_runner_sp_from_result(runner)

        manual_return = None
        ret, pl = calculate_return_and_pl(
            result_label,
            row.get("Odds_Taken"),
            row.get("Stake"),
            manual_return=manual_return,
        )

        ledger.loc[idx, "Result"] = result_label
        ledger.loc[idx, "Position"] = position
        if not pd.isna(sp):
            ledger.loc[idx, "SP"] = sp
            odds_taken = safe_num(row.get("Odds_Taken"), np.nan)
            if not pd.isna(odds_taken):
                ledger.loc[idx, "Market_Move"] = round(odds_taken - sp, 2)
                ledger.loc[idx, "Market_Move_Band"] = market_move_band(odds_taken - sp)
        ledger.loc[idx, "Return"] = ret
        ledger.loc[idx, "P/L"] = pl
        ledger.loc[idx, "Notes"] = f"{row.get('Notes', '')}; Auto-reconciled from {source} ({status})"

        audit_rows.append({
            "Horse": row.get("Horse"), "Course": row.get("Course"), "Time": row.get("Time"),
            "Status": status, "Result": result_label, "Position": position, "SP": sp,
            "Return": ret, "P/L": pl, "Updated": True
        })

    return ledger, pd.DataFrame(audit_rows), source


def analyse_racecards(racecards):
    selections = []

    ledger_for_calibration = load_ledger()
    _, combo_tbl, score_tbl, odds_tbl, overall_calibration = build_calibration_tables(ledger_for_calibration)

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
            heuristic_prob = estimate_probability(score, odds, market_move)
            estimated_prob, calibration_source = lookup_calibrated_probability(
                score, odds, heuristic_prob, combo_tbl, score_tbl, odds_tbl, overall_calibration
            )
            edge, ev = calculate_edge(estimated_prob, odds)
            strategy = assign_strategy(score, odds, edge, market_move)
            stake = calculate_stake(base_stake, odds, estimated_prob, edge)

            qualifies = qualifies_selection(strategy, odds, score, edge, market_move)

            failed_filters = []
            if odds < min_odds:
                failed_filters.append("Below min odds")
            if odds > max_odds:
                failed_filters.append("Above max odds")
            if qualification_mode != "Testing: show anything passing odds":
                if score < min_score:
                    failed_filters.append("Below min score")
                if pd.isna(edge) or edge < min_edge:
                    failed_filters.append("Below min edge")
            if require_steam:
                has_steam = not pd.isna(market_move) and market_move > 0
                if not has_steam and not (allow_longshots_without_steam and odds >= 10):
                    failed_filters.append("No steam")
            if qualification_mode == "Strict Semi-Pro":
                has_steam = not pd.isna(market_move) and market_move > 0
                strict_pass = (
                    (odds >= 10 and score >= 25) or
                    (5 <= odds < 10 and score >= 25 and has_steam) or
                    (score >= 30 and edge >= min_edge)
                )
                if not strict_pass:
                    failed_filters.append("Strict rules")

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
                "Heuristic_Prob": heuristic_prob,
                "Calibration_Source": calibration_source,
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
                "Notes": f"Odds source: {odds_source}; Calibration: {calibration_source}",
                "Filter_Reason": "Pass" if qualifies else " | ".join(failed_filters),
                "Elite": is_elite,
                "Qualifies": qualifies,
            }
            selections.append(selection)

    return selections

# =========================================================
# 9. PERFORMANCE ANALYSIS
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

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🚀 Market Analysis", "📊 Ledger", "📈 Performance", "🧠 Calibration", "🧪 Debug / API Fields"
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

        if show_filter_diagnostics:
            st.subheader("🧪 Filter Diagnostics")
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Pass Odds", int(((df_all["Odds_Taken"] >= min_odds) & (df_all["Odds_Taken"] <= max_odds)).sum()))
            d2.metric("Pass Score", int((df_all["Score"] >= min_score).sum()))
            d3.metric("Pass Edge", int((df_all["Edge"] >= min_edge).sum()) if qualification_mode != "Testing: show anything passing odds" else "Bypassed")
            d4.metric("Qualifiers", int(df_all["Qualifies"].sum()))
            st.caption(
                f"Score range: {int(df_all['Score'].min())}–{int(df_all['Score'].max())} | "
                f"Median score: {df_all['Score'].median():.1f} | "
                f"Edge range: {df_all['Edge'].min():.1%} to {df_all['Edge'].max():.1%}"
            )
            if "Filter_Reason" in df_all.columns:
                st.dataframe(
                    df_all["Filter_Reason"].value_counts().reset_index().rename(columns={"index": "Filter Reason", "Filter_Reason": "Count"}),
                    use_container_width=True
                )

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
                "Market_Move", "Score", "Implied_Prob", "Heuristic_Prob", "Estimated_Prob", "Edge", "EV", "Stake", "Calibration_Source", "Filter_Reason", "Reason_Tags"
            ]
            st.dataframe(df_show[display_cols], use_container_width=True)

            st.markdown("### 🧾 Ledger Actions")
            log_col, view_col = st.columns([1, 1])

            with log_col:
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

                        ledger_key = make_selection_key(ledger) if not ledger.empty else pd.Series(dtype=str)
                        new_key = make_selection_key(new_df)

                        to_add = new_df[~new_key.isin(set(ledger_key))]
                        updated = pd.concat([ledger, to_add], ignore_index=True)
                        if update_ledger(updated):
                            st.success(f"Logged {len(to_add)} new selections. Skipped {len(new_df) - len(to_add)} duplicates.")
                            st.balloons()

            with view_col:
                if st.button("📋 Show Today’s Pending Qualifiers", use_container_width=True):
                    ledger = load_ledger()
                    today = datetime.now().strftime("%Y-%m-%d")
                    pending_today = ledger[
                        (ledger["Date"].astype(str) == today) &
                        (ledger["Result"].astype(str).str.lower().eq("pending"))
                    ]
                    if pending_today.empty:
                        st.info("No pending qualifiers logged for today.")
                    else:
                        st.dataframe(pending_today[["Date", "Horse", "Course", "Time", "Odds_Taken", "Stake", "Bet_Type", "Score", "Edge"]], use_container_width=True)

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

    st.markdown("### 🔄 Auto-Reconcile Results")
    ar1, ar2, ar3 = st.columns([1, 1, 2])
    with ar1:
        reconcile_date = st.date_input("Results date", value=date.today())
    with ar2:
        st.write("")
        st.write("")
        auto_button = st.button("🔄 Auto-Reconcile Pending Results", use_container_width=True)

    if auto_button:
        target_date = reconcile_date.strftime("%Y-%m-%d")
        with st.spinner(f"Fetching official results and reconciling pending selections for {target_date}..."):
            updated_ledger, audit_df, source_msg = auto_reconcile_pending_results(target_date)
            if audit_df.empty:
                st.warning(source_msg)
            else:
                if update_ledger(updated_ledger):
                    updated_count = int(audit_df["Updated"].sum()) if "Updated" in audit_df.columns else 0
                    st.success(f"Auto-reconciled {updated_count} selections. Source: {source_msg}")
                    st.dataframe(audit_df, use_container_width=True)
                    if updated_count > 0:
                        st.rerun()

    st.divider()
    st.markdown("### ✅ Manual Reconcile Pending Qualifiers")
    pending = ledger[ledger["Result"].astype(str).str.lower().eq("pending")].copy()

    if pending.empty:
        st.info("No pending qualifiers to reconcile.")
    else:
        pending["Selection_Label"] = (
            pending["Date"].astype(str) + " — " +
            pending["Time"].astype(str) + " " +
            pending["Course"].astype(str) + " — " +
            pending["Horse"].astype(str) + " @ " +
            pending["Odds_Taken"].astype(str)
        )

        selected_label = st.selectbox(
            "Choose a qualifier to reconcile",
            pending["Selection_Label"].tolist(),
            index=0,
        )

        selected_idx = pending[pending["Selection_Label"] == selected_label].index[0]
        selected_row = ledger.loc[selected_idx]

        r1, r2, r3, r4 = st.columns(4)
        with r1:
            result_input = st.selectbox("Result", ["Win", "Lose", "Placed", "Void", "Non-Runner"], index=1)
        with r2:
            position_input = st.number_input("Finishing Position", min_value=0, value=0, step=1)
        with r3:
            sp_input = st.number_input(
                "SP / BSP",
                min_value=0.0,
                value=float(safe_num(selected_row.get("SP"), 0) or 0),
                step=0.1,
            )
        with r4:
            manual_return_input = st.number_input(
                "Return (£)",
                min_value=0.0,
                value=0.0,
                step=0.5,
                help="Use this for Each-Way, Place, 80/20 or any settled return. For simple Win bets, leave 0 and the app can calculate automatically."
            )

        notes_input = st.text_area("Settlement Notes", value=str(selected_row.get("Notes", "") or ""), height=80)

        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            if st.button("✅ Save Result", use_container_width=True):
                manual_return = manual_return_input if manual_return_input > 0 else None
                ret, pl = calculate_return_and_pl(
                    result_input,
                    selected_row.get("Odds_Taken"),
                    selected_row.get("Stake"),
                    manual_return=manual_return,
                )

                ledger.loc[selected_idx, "Result"] = result_input
                ledger.loc[selected_idx, "Position"] = position_input
                ledger.loc[selected_idx, "SP"] = sp_input if sp_input > 0 else selected_row.get("SP")
                ledger.loc[selected_idx, "Return"] = ret
                ledger.loc[selected_idx, "P/L"] = pl
                ledger.loc[selected_idx, "Notes"] = notes_input

                # Closing line value / market movement: positive means you beat SP/BSP.
                odds_taken = safe_num(selected_row.get("Odds_Taken"), np.nan)
                if sp_input > 1 and not pd.isna(odds_taken):
                    ledger.loc[selected_idx, "Market_Move"] = round(odds_taken - sp_input, 2)
                    ledger.loc[selected_idx, "Market_Move_Band"] = market_move_band(odds_taken - sp_input)

                if update_ledger(ledger):
                    st.success(f"Updated {selected_row.get('Horse')} — Return £{ret:.2f}, P/L £{pl:.2f}")
                    st.rerun()

        with c2:
            if st.button("↩️ Mark as Pending", use_container_width=True):
                ledger.loc[selected_idx, "Result"] = "Pending"
                ledger.loc[selected_idx, "Position"] = np.nan
                ledger.loc[selected_idx, "Return"] = 0.0
                ledger.loc[selected_idx, "P/L"] = 0.0
                if update_ledger(ledger):
                    st.success("Selection reset to Pending.")
                    st.rerun()

        st.caption("Tip: for Each-Way, Place or 80/20 bets, type the bookmaker/exchange settled return into Return (£) for accurate P/L.")

    st.divider()
    st.markdown("### Full Ledger")
    st.dataframe(ledger, use_container_width=True)

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
    st.subheader("🧠 Auto-Calibration")
    ledger = load_ledger()
    _, combo_tbl, score_tbl, odds_tbl, overall = build_calibration_tables(ledger)

    if overall is None:
        st.info("No settled results available yet. Calibration will use the heuristic probability model only.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Settled calibration sample", overall["samples"])
        c2.metric("Overall win rate", f"{overall['win_rate']:.1%}")
        c3.metric("Average odds", f"{overall['avg_odds']:.2f}")

        st.caption(
            "The app now looks for historical win rates in this order: Score+Odds bucket → Score bucket → Odds bucket → Overall ledger. "
            "Tiny buckets are smoothed so one lucky winner does not distort the model."
        )

        st.markdown("### Score + Odds Calibration")
        if combo_tbl.empty:
            st.info("No score+odds calibration table yet.")
        else:
            st.dataframe(combo_tbl.sort_values(["Score_Band", "Odds_Band"]), use_container_width=True)

        st.markdown("### Score Band Calibration")
        if score_tbl.empty:
            st.info("No score-band calibration table yet.")
        else:
            st.dataframe(score_tbl.sort_values("Score_Band"), use_container_width=True)

        st.markdown("### Odds Band Calibration")
        if odds_tbl.empty:
            st.info("No odds-band calibration table yet.")
        else:
            st.dataframe(odds_tbl.sort_values("Odds_Band"), use_container_width=True)

        st.warning(
            "Calibration is only as good as the data in your ledger. Treat it as experimental until you have at least 100–300 settled bets."
        )

with tab5:
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
