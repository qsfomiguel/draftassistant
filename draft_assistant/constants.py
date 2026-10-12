"""ESPN fantasy basketball id mappings."""

STAT_NAMES = {
    0: "PTS", 1: "BLK", 2: "STL", 3: "AST", 4: "OREB", 5: "DREB", 6: "REB",
    7: "EJ", 8: "FF", 9: "PF", 10: "TF", 11: "TO", 12: "DQ", 13: "FGM",
    14: "FGA", 15: "FTM", 16: "FTA", 17: "3PM", 18: "3PA", 19: "FG%",
    20: "FT%", 21: "3P%", 22: "AFG%", 23: "FGMI", 24: "FTMI", 25: "3PMI",
    26: "APG", 27: "BPG", 28: "MPG", 29: "PPG", 30: "RPG", 31: "SPG",
    32: "TOPG", 33: "3PG", 34: "PPM", 35: "A/TO", 36: "STR", 37: "DD",
    38: "TD", 39: "QD", 40: "MIN", 41: "GS", 42: "GP", 43: "TW", 44: "FTR",
}
STAT_IDS = {name: sid for sid, name in STAT_NAMES.items()}

GP = 42

# Percentage categories are valued by volume: (makes id, attempts id).
PERCENT_STATS = {19: (13, 14), 20: (15, 16), 21: (17, 18)}

SLOT_NAMES = {
    0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F",
    7: "SG/SF", 8: "G/F", 9: "PF/C", 10: "F/C", 11: "UT", 12: "BE", 13: "IR",
}
BENCH_SLOT = 12
IR_SLOT = 13
POSITION_SLOTS = (0, 1, 2, 3, 4)

PRO_TEAMS = {
    0: "FA", 1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GSW", 10: "HOU", 11: "IND", 12: "LAC", 13: "LAL",
    14: "MIA", 15: "MIL", 16: "MIN", 17: "BKN", 18: "NYK", 19: "ORL",
    20: "PHI", 21: "PHX", 22: "POR", 23: "SAC", 24: "SAS", 25: "OKC",
    26: "UTA", 27: "WAS", 28: "TOR", 29: "MEM", 30: "CHA",
}

POINTS_SCORING = {"H2H_POINTS", "POINTS"}
