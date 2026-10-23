#!/usr/bin/env python3
"""
Fetch NBA box scores and calculate Terry Awards (worst player) and Jokic Awards (best player).
Uses PlayerGameLogs bulk endpoint for fast full-season fetches.
"""

import json
import time
from datetime import datetime
from pathlib import Path

from nba_api.stats.endpoints import playergamelogs
from requests.exceptions import ReadTimeout, ConnectionError

# Terry Score weights
WEIGHTS = {
    "MIN": -0.2,
    "PLUS_MINUS": 0.5,
    "WL": 5,
    "FGM": 2,
    "FGA": -1.2,
    "FG3M": 2,
    "FG3A": -0.7,
    "FTM": 2,
    "FTA": -1.5,
    "REB": 2,
    "AST": 2.5,
    "STL": 1,
    "BLK": 1,
    "TO": -4,
    "PF": -0.5,
    "PTS": 0.5,
}

DATA_DIR = Path(__file__).parent / "data"


def parse_minutes(min_val):
    """Parse minutes — could be float (from MIN column) or string like '34:05'."""
    if min_val is None or (isinstance(min_val, float) and min_val != min_val):  # NaN check
        return 0.0
    if isinstance(min_val, (int, float)):
        return float(min_val)
    s = str(min_val)
    if ":" in s:
        parts = s.split(":")
        return float(parts[0]) + float(parts[1]) / 60.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def calculate_terry_score(row):
    """Calculate Terry/Jokic score from a PlayerGameLogs row."""
    minutes = parse_minutes(row.get("MIN", 0))
    won = row.get("WL") == "W"
    score = (
        minutes * WEIGHTS["MIN"]
        + float(row.get("PLUS_MINUS", 0) or 0) * WEIGHTS["PLUS_MINUS"]
        + (1 if won else 0) * WEIGHTS["WL"]
        + float(row.get("FGM", 0) or 0) * WEIGHTS["FGM"]
        + float(row.get("FGA", 0) or 0) * WEIGHTS["FGA"]
        + float(row.get("FG3M", 0) or 0) * WEIGHTS["FG3M"]
        + float(row.get("FG3A", 0) or 0) * WEIGHTS["FG3A"]
        + float(row.get("FTM", 0) or 0) * WEIGHTS["FTM"]
        + float(row.get("FTA", 0) or 0) * WEIGHTS["FTA"]
        + float(row.get("REB", 0) or 0) * WEIGHTS["REB"]
        + float(row.get("AST", 0) or 0) * WEIGHTS["AST"]
        + float(row.get("STL", 0) or 0) * WEIGHTS["STL"]
        + float(row.get("BLK", 0) or 0) * WEIGHTS["BLK"]
        + float(row.get("TOV", 0) or 0) * WEIGHTS["TO"]
        + float(row.get("PF", 0) or 0) * WEIGHTS["PF"]
        + float(row.get("PTS", 0) or 0) * WEIGHTS["PTS"]
    )
    return round(score, 1)


def parse_matchup(matchup):
    """Parse matchup like 'BOS @ DET' or 'DET vs. BOS' into (team, home_away, opp)."""
    if " vs. " in matchup:
        parts = matchup.split(" vs. ")
        return parts[0].strip(), "vs", parts[1].strip()
    elif " @ " in matchup:
        parts = matchup.split(" @ ")
        return parts[0].strip(), "@", parts[1].strip()
    return matchup, "", ""


def row_to_player_dict(row, is_playoff):
    """Convert a DataFrame row to our player dict format."""
    team, home_away, opp = parse_matchup(row.get("MATCHUP", ""))
    minutes = parse_minutes(row.get("MIN", 0))
    return {
        "player_name": row["PLAYER_NAME"],
        "player_id": int(row["PLAYER_ID"]),
        "team": row["TEAM_ABBREVIATION"],
        "opp": opp,
        "home_away": home_away,
        "won": row.get("WL") == "W",
        "min": round(minutes, 1),
        "pts": int(row.get("PTS", 0) or 0),
        "reb": int(row.get("REB", 0) or 0),
        "ast": int(row.get("AST", 0) or 0),
        "stl": int(row.get("STL", 0) or 0),
        "blk": int(row.get("BLK", 0) or 0),
        "to": int(row.get("TOV", 0) or 0),
        "pf": int(row.get("PF", 0) or 0),
        "fgm": int(row.get("FGM", 0) or 0),
        "fga": int(row.get("FGA", 0) or 0),
        "fg3m": int(row.get("FG3M", 0) or 0),
        "fg3a": int(row.get("FG3A", 0) or 0),
        "ftm": int(row.get("FTM", 0) or 0),
        "fta": int(row.get("FTA", 0) or 0),
        "plus_minus": float(row.get("PLUS_MINUS", 0) or 0),
        "on_off": float(row.get("ON_OFF", 0) or 0),
        "team_score": int(row.get("TEAM_PTS_TOTAL", 0) or 0),
        "opp_score": int(row.get("OPP_PTS_TOTAL", 0) or 0),
        "terry_score": calculate_terry_score(row),
        "is_playoff": is_playoff,
    }


def fetch_with_retry(api_season, max_retries=3, timeout=120):
    """Fetch PlayerGameLogs with retry logic."""
    for attempt in range(1, max_retries + 1):
        try:
            print(f"  Attempt {attempt}/{max_retries} (timeout={timeout}s)...")
            logs = playergamelogs.PlayerGameLogs(
                season_nullable=api_season,
                league_id_nullable="00",
                timeout=timeout,
            )
            return logs.get_data_frames()[0]
        except (ReadTimeout, ConnectionError) as e:
            print(f"  Attempt {attempt} failed: {e}")
            if attempt == max_retries:
                raise
            wait = 30 * attempt
            print(f"  Retrying in {wait}s...")
            time.sleep(wait)


def update_season(season_start_year):
    """Fetch full season data in one bulk call."""
    season_key = f"{season_start_year}-{str(season_start_year + 1)[-2:]}"
    api_season = f"{season_start_year}-{str(season_start_year + 1)[-2:]}"
    print(f"\nFetching season {season_key} (bulk)...")

    df = fetch_with_retry(api_season)
    print(f"  Got {len(df)} player-game rows")

    if df.empty:
        print("  No data found")
        return

    # Filter to regular season + playoffs (exclude preseason)
    df = df[df["GAME_ID"].str.startswith(("002", "004"))]
    print(f"  After filtering preseason: {len(df)} rows")

    # Tag playoff vs regular season
    df["IS_PLAYOFF"] = df["GAME_ID"].str.startswith("004")

    # Compute team scores and margin per game (before min filter so totals are accurate)
    df["MIN_FLOAT"] = df["MIN"].apply(parse_minutes)
    team_scores = df.groupby(["GAME_ID", "TEAM_ID"])["PTS"].sum().reset_index()
    team_scores.columns = ["GAME_ID", "TEAM_ID", "TEAM_PTS"]

    # For each game, get both teams' scores
    game_teams = team_scores.groupby("GAME_ID").apply(
        lambda g: dict(zip(g["TEAM_ID"], g["TEAM_PTS"]))
    ).to_dict()

    # Compute team margin and on/off for each player row
    def calc_margin_and_onoff(row):
        gid = row["GAME_ID"]
        tid = row["TEAM_ID"]
        teams = game_teams.get(gid, {})
        team_pts = teams.get(tid, 0)
        opp_pts = sum(v for k, v in teams.items() if k != tid)
        margin = int(team_pts - opp_pts)
        on_off = float(row.get("PLUS_MINUS", 0) or 0) - margin
        return margin, round(on_off, 1), int(team_pts), int(opp_pts)

    margins = df.apply(calc_margin_and_onoff, axis=1, result_type="expand")
    df["MARGIN"] = margins[0]
    df["ON_OFF"] = margins[1]
    df["TEAM_PTS_TOTAL"] = margins[2]
    df["OPP_PTS_TOTAL"] = margins[3]

    # Now filter min >= 5 minutes
    df = df[df["MIN_FLOAT"] >= 5]
    print(f"  After filtering < 5 min: {len(df)} rows")

    # Parse dates
    df["DATE"] = df["GAME_DATE"].str[:10]  # "2025-10-21T00:00:00" -> "2025-10-21"

    # Group by date
    data = {"season": season_key, "dates": {}}
    dates = sorted(df["DATE"].unique())

    for date_str in dates:
        day_df = df[df["DATE"] == date_str]
        players = [row_to_player_dict(row, bool(row["IS_PLAYOFF"])) for _, row in day_df.iterrows()]
        players.sort(key=lambda x: x["terry_score"])

        terry_winner = players[0]
        jokic_winner = players[-1]
        display_str = f"{int(date_str[5:7])}/{int(date_str[8:10])}"

        is_playoff = any(p["is_playoff"] for p in players)
        data["dates"][date_str] = {
            "display_date": display_str,
            "is_playoff": is_playoff,
            "terry_winner": terry_winner,
            "jokic_winner": jokic_winner,
            "bottom_10": players[:10],
            "top_10": players[-10:][::-1],
            "total_players": len(players),
        }

    print(f"  Processed {len(dates)} game dates")

    # Save
    DATA_DIR.mkdir(exist_ok=True)
    filepath = DATA_DIR / f"{season_key}.json"
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Saved {filepath}")

    # Save compact raw data for client-side recalculation
    # Format: columns header + array rows for minimal size
    raw_rows = []
    for _, row in df.iterrows():
        minutes = parse_minutes(row.get("MIN", 0))
        team, home_away, opp = parse_matchup(row.get("MATCHUP", ""))
        raw_rows.append([
            row["DATE"],                              # 0: date
            int(row["PLAYER_ID"]),                    # 1: player_id
            row["PLAYER_NAME"],                       # 2: player_name
            row["TEAM_ABBREVIATION"],                 # 3: team
            opp,                                      # 4: opp
            home_away,                                # 5: home_away
            1 if row.get("WL") == "W" else 0,        # 6: won
            round(minutes, 1),                        # 7: min
            int(row.get("FGM", 0) or 0),              # 8: fgm
            int(row.get("FGA", 0) or 0),              # 9: fga
            int(row.get("FG3M", 0) or 0),             # 10: fg3m
            int(row.get("FG3A", 0) or 0),             # 11: fg3a
            int(row.get("FTM", 0) or 0),              # 12: ftm
            int(row.get("FTA", 0) or 0),              # 13: fta
            int(row.get("REB", 0) or 0),              # 14: reb
            int(row.get("AST", 0) or 0),              # 15: ast
            int(row.get("STL", 0) or 0),              # 16: stl
            int(row.get("BLK", 0) or 0),              # 17: blk
            int(row.get("TOV", 0) or 0),              # 18: to
            int(row.get("PF", 0) or 0),               # 19: pf
            int(row.get("PTS", 0) or 0),              # 20: pts
            float(row.get("PLUS_MINUS", 0) or 0),     # 21: plus_minus
            1 if bool(row["IS_PLAYOFF"]) else 0,      # 22: is_playoff
            float(row.get("ON_OFF", 0) or 0),         # 23: on_off
            int(row.get("TEAM_PTS_TOTAL", 0) or 0),   # 24: team_score
            int(row.get("OPP_PTS_TOTAL", 0) or 0),    # 25: opp_score
        ])
    raw_data = {
        "cols": ["date","player_id","player_name","team","opp","home_away","won","min","fgm","fga","fg3m","fg3a","ftm","fta","reb","ast","stl","blk","to","pf","pts","plus_minus","is_playoff","on_off","team_score","opp_score"],
        "rows": raw_rows,
    }
    raw_filepath = DATA_DIR / f"{season_key}_raw.json"
    with open(raw_filepath, "w") as f:
        json.dump(raw_data, f)
    print(f"  Saved {raw_filepath} ({len(raw_rows)} rows)")

    # Compute per-player season aggregates from the full dataframe
    player_aggs = compute_player_aggregates(df)

    generate_summary(data, season_key, player_aggs)
    return data


def compute_player_aggregates(df):
    """Compute cumulative terry score, games, avg for every player in the season."""
    df = df.copy()
    df["TERRY"] = df.apply(calculate_terry_score, axis=1)

    aggs = {}
    for _, row in df.iterrows():
        pid = int(row["PLAYER_ID"])
        is_po = bool(row["IS_PLAYOFF"])
        terry = row["TERRY"]
        if pid not in aggs:
            aggs[pid] = {
                "player_id": pid,
                "player_name": row["PLAYER_NAME"],
                "team": row["TEAM_ABBREVIATION"],
                "games": 0,
                "playoff_games": 0,
                "total_terry": 0.0,
                "reg_games": 0,
                "reg_total_terry": 0.0,
            }
        aggs[pid]["games"] += 1
        aggs[pid]["total_terry"] += terry
        aggs[pid]["team"] = row["TEAM_ABBREVIATION"]  # most recent
        if is_po:
            aggs[pid]["playoff_games"] += 1
        else:
            aggs[pid]["reg_games"] += 1
            aggs[pid]["reg_total_terry"] += terry

    # Round and compute per-game
    for pid, a in aggs.items():
        a["total_terry"] = round(a["total_terry"], 1)
        a["reg_total_terry"] = round(a["reg_total_terry"], 1)
        a["terry_per_game"] = round(a["total_terry"] / a["games"], 1) if a["games"] > 0 else 0
        a["reg_terry_per_game"] = round(a["reg_total_terry"] / a["reg_games"], 1) if a["reg_games"] > 0 else 0

    return aggs


def generate_summary(data, season_key, player_aggs=None):
    """Generate summary stats: repeat offenders, records, etc."""
    terry_offenders = {}
    jokic_offenders = {}
    all_terry_scores = []
    all_jokic_scores = []

    for date_str, day_data in sorted(data["dates"].items()):
        tw = day_data["terry_winner"]
        jw = day_data["jokic_winner"]
        is_playoff = day_data.get("is_playoff", False)

        name = tw["player_name"]
        if name not in terry_offenders:
            terry_offenders[name] = {"count": 0, "playoff_count": 0, "dates": [], "player_id": tw["player_id"], "team": tw["team"], "worst_score": tw["terry_score"], "total_offense_terry": 0.0}
        terry_offenders[name]["count"] += 1
        terry_offenders[name]["total_offense_terry"] += tw["terry_score"]
        if is_playoff:
            terry_offenders[name]["playoff_count"] += 1
        terry_offenders[name]["dates"].append({"date": date_str, "is_playoff": is_playoff, "terry_score": tw["terry_score"]})
        terry_offenders[name]["team"] = tw["team"]
        terry_offenders[name]["worst_score"] = min(terry_offenders[name]["worst_score"], tw["terry_score"])

        name = jw["player_name"]
        if name not in jokic_offenders:
            jokic_offenders[name] = {"count": 0, "playoff_count": 0, "dates": [], "player_id": jw["player_id"], "team": jw["team"], "best_score": jw["terry_score"], "total_offense_terry": 0.0}
        jokic_offenders[name]["count"] += 1
        jokic_offenders[name]["total_offense_terry"] += jw["terry_score"]
        if is_playoff:
            jokic_offenders[name]["playoff_count"] += 1
        jokic_offenders[name]["dates"].append({"date": date_str, "is_playoff": is_playoff, "terry_score": jw["terry_score"]})
        jokic_offenders[name]["team"] = jw["team"]
        jokic_offenders[name]["best_score"] = max(jokic_offenders[name]["best_score"], jw["terry_score"])

        all_terry_scores.append({"date": date_str, "is_playoff": is_playoff, **tw})
        all_jokic_scores.append({"date": date_str, "is_playoff": is_playoff, **jw})

    # Add avg offense terry score
    for name, info in terry_offenders.items():
        info["avg_offense_terry"] = round(info["total_offense_terry"] / info["count"], 1) if info["count"] > 0 else 0
    for name, info in jokic_offenders.items():
        info["avg_offense_terry"] = round(info["total_offense_terry"] / info["count"], 1) if info["count"] > 0 else 0

    terry_leaderboard = sorted(terry_offenders.items(), key=lambda x: (-x[1]["count"], x[1]["worst_score"]))
    jokic_leaderboard = sorted(jokic_offenders.items(), key=lambda x: (-x[1]["count"], -x[1]["best_score"]))

    worst_ever = min(all_terry_scores, key=lambda x: x["terry_score"]) if all_terry_scores else None
    best_ever = max(all_jokic_scores, key=lambda x: x["terry_score"]) if all_jokic_scores else None

    # Build player season stats lists (sorted worst to best for terry, best to worst for jokic)
    cumulative_worst = sorted(player_aggs.values(), key=lambda x: x["total_terry"]) if player_aggs else []
    cumulative_best = sorted(player_aggs.values(), key=lambda x: -x["total_terry"]) if player_aggs else []
    min_games = max(5, len(data["dates"]) // 10)  # ~10% of season games, min 5
    per_game_worst = sorted([p for p in player_aggs.values() if p["games"] >= min_games], key=lambda x: x["terry_per_game"]) if player_aggs else []
    per_game_best = sorted([p for p in player_aggs.values() if p["games"] >= min_games], key=lambda x: -x["terry_per_game"]) if player_aggs else []

    summary = {
        "season": season_key,
        "total_nights": len(data["dates"]),
        "terry_leaderboard": [{"player": name, **info} for name, info in terry_leaderboard],
        "jokic_leaderboard": [{"player": name, **info} for name, info in jokic_leaderboard],
        "worst_ever": worst_ever,
        "best_ever": best_ever,
        "terry_history": sorted(all_terry_scores, key=lambda x: x["date"], reverse=True),
        "jokic_history": sorted(all_jokic_scores, key=lambda x: x["date"], reverse=True),
        "cumulative_worst": cumulative_worst[:50],
        "cumulative_best": cumulative_best[:50],
        "per_game_worst": per_game_worst[:50],
        "per_game_best": per_game_best[:50],
    }

    filepath = DATA_DIR / f"{season_key}_summary.json"
    with open(filepath, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Saved {filepath}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Update Terry Awards data")
    parser.add_argument("--season", type=int, help="Season start year (e.g. 2026 for 2026-27)")
    parser.add_argument("--seasons", type=str, help="Comma-separated season start years (e.g. 2024,2025,2026)")
    args = parser.parse_args()

    if args.seasons:
        years = [int(y.strip()) for y in args.seasons.split(",")]
    elif args.season:
        years = [args.season]
    else:
        now = datetime.now()
        current_season_year = now.year if now.month >= 10 else now.year - 1
        years = [current_season_year]

    for year in years:
        update_season(year)
        time.sleep(2)  # brief pause between seasons

    # Generate seasons index
    season_files = sorted(DATA_DIR.glob("*_summary.json"))
    seasons_index = [f.stem.replace("_summary", "") for f in season_files]
    with open(DATA_DIR / "seasons.json", "w") as f:
        json.dump(seasons_index, f)
    print(f"\nSeasons index: {seasons_index}")


if __name__ == "__main__":
    main()
