#!/usr/bin/env python3
"""
statedb.py — one SQLite (WAL) database for all shared run-state (feature-roadmap H.4).

WHY THIS EXISTS. Run-state lives in ~8 CSV/JSONL files plus a lock-file zoo, each with its own
truncate-on-throw scar and no way to ask a cross-file question ("blocked rows by ATS whose
proof is missing", "conversion by family over time"). One SQLite DB gives transactions (the
data-loss class dies structurally, not with more advisory locks), cross-table queries, and
history — while the CSVs become generated, human-readable EXPORTS.

MIGRATION POSTURE (deliberate, per the roadmap). This is the FOUNDATION + a two-way SYNC, not
a rip-out: the shipped CSV writers (board_cooldown/apply_stats/log-application/…) already have
atomic+locked writes and are load-bearing for the live daily loop, so cutting them all over in
one change would be reckless. Instead:
  * `import-csvs` loads the current CSVs into state.db (idempotent, transactional),
  * `export <table>` writes a table back to its CSV shape,
  * the cross-table query helpers + `query` CLI run over the DB.
A module is migrated to read/write the DB directly TABLE-AT-A-TIME in a quiet period; until
then the CSV is source-of-truth and `import-csvs` (cron) keeps the DB warm for analytics.
WAL mode + a transaction per import means a reader never sees a half-written DB.

Tables mirror the CSVs (columns kept identical so export is loss-free):
  applications(date,company,role,source,url,status,next_action,notes)
  cooldowns(board,query,checked_at,cooldown_until)
  yields(ts,board,query,n_fresh)
  apply_stats(ats,attempts,submitted,last)
  screener(pattern,kind,answer,source)
  accounts(key,ats,board,blocked_count,est_inventory,first_seen,last_seen,signup_url,note)
  outcome_stats(dimension,key,applied,responses,positive,rate,updated)

CLI:
  statedb.py import-csvs                 # load all present CSVs into state.db
  statedb.py export <table> [path]       # write a table back to CSV
  statedb.py query "SELECT ..."          # ad-hoc read-only SQL
  statedb.py tables                      # list tables + row counts
  statedb.py blocked-by-ats              # cross-table example: Blocked rows grouped by ATS
"""
import csv
import os
import sqlite3
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_here, "..", "..", ".."))
DB = os.path.join(_ROOT, "state.db")

# table -> (csv filename, columns). Columns match the CSV headers exactly (loss-free export).
TABLES = {
    "applications": ("application-tracker.csv",
                     ["date", "company", "role", "source", "url", "status", "next_action", "notes"]),
    "cooldowns": ("board-cooldown.csv", ["board", "query", "checked_at", "cooldown_until"]),
    "yields": ("search-yields.csv", ["ts", "board", "query", "n_fresh"]),
    "apply_stats": ("apply-stats.csv", ["ats", "attempts", "submitted", "last"]),
    "screener": ("screener-answers.csv", ["pattern", "kind", "answer", "source"]),
    "accounts": ("accounts-needed.csv",
                 ["key", "ats", "board", "blocked_count", "est_inventory",
                  "first_seen", "last_seen", "signup_url", "note"]),
    "outcome_stats": ("outcome-stats.csv",
                      ["dimension", "key", "applied", "responses", "positive", "rate", "updated"]),
}
# CSV header (original case/spacing) -> db column, per table where they differ.
_CSV_HEADER = {
    "applications": {"Date": "date", "Company": "company", "Role": "role", "Source": "source",
                     "URL": "url", "Status": "status", "Next Action": "next_action",
                     "Notes": "notes"},
}


def connect():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _ensure_schema(conn):
    for table, (_csvname, cols) in TABLES.items():
        coldefs = ", ".join(f'"{c}" TEXT' for c in cols)
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({coldefs})')
    conn.commit()


def _read_csv(csvname, cols, table):
    path = os.path.join(_ROOT, csvname)
    rows = []
    header_map = _CSV_HEADER.get(table, {})
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out = {}
                for c in cols:
                    # find the source header: reverse the header_map, else title/exact/lower
                    src = next((h for h, dbc in header_map.items() if dbc == c), None)
                    if src is None:
                        src = c if c in r else c.title() if c.title() in r else None
                    out[c] = (r.get(src) if src else r.get(c)) or ""
                rows.append(out)
    except (FileNotFoundError, OSError):
        pass
    return rows


def import_csvs():
    """Load every present CSV into state.db in ONE transaction per table (idempotent:
    replaces the table contents). Returns {table: rowcount}."""
    conn = connect()
    _ensure_schema(conn)
    counts = {}
    for table, (csvname, cols) in TABLES.items():
        rows = _read_csv(csvname, cols, table)
        with conn:  # transaction
            conn.execute(f'DELETE FROM "{table}"')
            if rows:
                ph = ", ".join("?" for _ in cols)
                conn.executemany(
                    f'INSERT INTO "{table}" ({", ".join(chr(34)+c+chr(34) for c in cols)}) VALUES ({ph})',
                    [[r[c] for c in cols] for r in rows])
        counts[table] = len(rows)
    conn.close()
    return counts


def export(table, path=None):
    """Write a table back to its CSV shape (original headers)."""
    if table not in TABLES:
        raise ValueError(f"unknown table {table!r}")
    csvname, cols = TABLES[table]
    path = path or os.path.join(_ROOT, csvname)
    header_map = _CSV_HEADER.get(table, {})
    headers = [next((h for h, dbc in header_map.items() if dbc == c), c) for c in cols]
    conn = connect()
    _ensure_schema(conn)
    rows = conn.execute(f'SELECT {", ".join(chr(34)+c+chr(34) for c in cols)} FROM "{table}"').fetchall()
    conn.close()
    from fsutil import file_lock, atomic_write

    def _w(f):
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    with file_lock(path):
        atomic_write(path, _w)
    return len(rows)


def blocked_by_ats():
    """Cross-table example (the kind of question CSVs can't answer): Blocked applications
    grouped by inferred ATS, joined against the accounts queue. Returns rows."""
    conn = connect()
    _ensure_schema(conn)
    rows = conn.execute(
        'SELECT source, COUNT(*) n FROM applications '
        'WHERE TRIM(status)="Blocked" GROUP BY source ORDER BY n DESC').fetchall()
    conn.close()
    return rows


def _cli(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "import-csvs":
        counts = import_csvs()
        print("imported into state.db:")
        for t, n in counts.items():
            print(f"  {t:<14} {n} rows")
        return 0
    if cmd == "export" and len(argv) >= 3:
        n = export(argv[2], argv[3] if len(argv) > 3 else None)
        print(f"exported {n} rows from {argv[2]}")
        return 0
    if cmd == "tables":
        conn = connect(); _ensure_schema(conn)
        for t in TABLES:
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            print(f"{t:<14} {n}")
        conn.close()
        return 0
    if cmd == "query" and len(argv) >= 3:
        conn = connect(); _ensure_schema(conn)
        try:
            for row in conn.execute(argv[2]).fetchall():
                print("\t".join(str(x) for x in row))
        except sqlite3.Error as e:
            print(f"SQL error: {e}", file=sys.stderr); return 2
        finally:
            conn.close()
        return 0
    if cmd == "blocked-by-ats":
        for source, n in blocked_by_ats():
            print(f"{source or '(none)':<40} {n}")
        return 0
    print("Usage: statedb.py import-csvs | export <table> [path] | tables | "
          "query \"SELECT ...\" | blocked-by-ats", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
