import json
import os
import sqlite3
from datetime import datetime, timezone
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "fleek_portfolio.sqlite")

EXPECTED_COLUMNS = [
    "account_id", "ownership", "buyer_persona", "region", "country", "account_status",
    "tenure_months", "gmv_total_6m", "orders_6m", "gmv_sep", "gmv_oct", "gmv_nov",
    "gmv_dec", "gmv_jan", "gmv_feb", "gmv_trend_pct", "broker_reliance_pct",
    "manual_orders", "self_serve_orders", "app_active_days_6m", "pdp_views_6m",
    "make_an_offer_6m", "chat_threads", "video_call_requests", "handpick_orders",
    "bundle_orders", "bundle_gmv_share_pct"
]

NUMERIC_COLUMNS = [
    "tenure_months", "gmv_total_6m", "orders_6m", "gmv_sep", "gmv_oct", "gmv_nov",
    "gmv_dec", "gmv_jan", "gmv_feb", "gmv_trend_pct", "broker_reliance_pct",
    "manual_orders", "self_serve_orders", "app_active_days_6m", "pdp_views_6m",
    "make_an_offer_6m", "chat_threads", "video_call_requests", "handpick_orders",
    "bundle_orders", "bundle_gmv_share_pct"
]
TEXT_COLUMNS = ["account_id", "ownership", "buyer_persona", "region", "country", "account_status"]

def _connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            account_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_source TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS action_state (
            account_id TEXT NOT NULL,
            action_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            note TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (account_id, action_key)
        )
    """)
    # Existing demo databases are migrated without losing saved action states.
    cols = {r[1] for r in con.execute("PRAGMA table_info(action_state)").fetchall()}
    if "draft_override" not in cols:
        con.execute("ALTER TABLE action_state ADD COLUMN draft_override TEXT")
    con.execute("""
        CREATE TABLE IF NOT EXISTS import_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imported_at TEXT NOT NULL,
            source TEXT NOT NULL,
            received INTEGER NOT NULL,
            inserted INTEGER NOT NULL,
            updated INTEGER NOT NULL,
            unchanged INTEGER NOT NULL,
            rejected INTEGER NOT NULL,
            quality_json TEXT NOT NULL
        )
    """)
    con.commit()
    return con

def get_database_path():
    return DB_PATH

def reset_demo_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    for suffix in ("-wal", "-shm"):
        candidate = DB_PATH + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    _connect().close()

def read_workbook(file_like):
    xls = pd.ExcelFile(file_like)
    return {name: pd.read_excel(xls, sheet_name=name) for name in xls.sheet_names}

def clean_accounts(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    # tolerate whitespace/case differences in source headers
    lower_to_original = {str(c).strip().lower(): c for c in df.columns}
    rename = {}
    for expected in EXPECTED_COLUMNS:
        if expected not in df.columns and expected.lower() in lower_to_original:
            rename[lower_to_original[expected.lower()]] = expected
    df = df.rename(columns=rename)

    missing_columns = [c for c in EXPECTED_COLUMNS if c not in df.columns]
    if missing_columns:
        raise ValueError("Missing expected columns: " + ", ".join(missing_columns))

    df = df[EXPECTED_COLUMNS]
    quality = {
        "rows_received": int(len(df)),
        "missing_account_id": int(df["account_id"].isna().sum()),
        "duplicate_account_ids_in_batch": int(df["account_id"].duplicated(keep="last").sum()),
        "missing_values_by_column": {
            c: int(n) for c, n in df.isna().sum().items() if int(n) > 0
        },
        "invalid_numeric_values_by_column": {}
    }

    for col in TEXT_COLUMNS:
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "NULL": pd.NA})

    for col in NUMERIC_COLUMNS:
        original_nonblank = df[col].notna()
        converted = pd.to_numeric(df[col], errors="coerce")
        invalid = original_nonblank & converted.isna()
        if invalid.any():
            quality["invalid_numeric_values_by_column"][col] = int(invalid.sum())
        df[col] = converted

    # Canonicalise known categorical values without guessing missing values.
    df["ownership"] = df["ownership"].replace({
        "account managed": "Account Managed",
        "account-managed": "Account Managed",
        "self serve": "Self Serve",
        "self-serve": "Self Serve",
    })
    df["buyer_persona"] = df["buyer_persona"].str.title()
    df["account_status"] = df["account_status"].str.title()

    # Rows without a stable ID cannot be safely upserted.
    df = df[df["account_id"].notna()].copy()
    # Last record in a batch wins if the same ID occurs more than once.
    df = df.drop_duplicates(subset=["account_id"], keep="last")
    quality["rows_after_validation"] = int(len(df))
    quality["rows_rejected_missing_id"] = quality["missing_account_id"]
    return df, quality

def ingest_accounts(df, source="upload", quality=None):
    quality = quality or {}
    inserted = updated = unchanged = rejected = 0
    now = datetime.now(timezone.utc).isoformat()
    con = _connect()
    try:
        with con:
            for _, row in df.iterrows():
                account_id = str(row["account_id"]).strip()
                if not account_id or account_id.lower() == "nan":
                    rejected += 1
                    continue
                payload = {}
                for col in EXPECTED_COLUMNS:
                    val = row[col]
                    if pd.isna(val):
                        payload[col] = None
                    elif col in NUMERIC_COLUMNS:
                        payload[col] = float(val) if col in ["gmv_trend_pct"] else float(val)
                    else:
                        payload[col] = str(val)
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                existing = con.execute(
                    "SELECT payload FROM accounts WHERE account_id = ?", (account_id,)
                ).fetchone()
                if existing is None:
                    con.execute(
                        "INSERT INTO accounts(account_id,payload,updated_at,last_source) VALUES(?,?,?,?)",
                        (account_id, encoded, now, source)
                    )
                    inserted += 1
                elif existing["payload"] == encoded:
                    unchanged += 1
                else:
                    con.execute(
                        "UPDATE accounts SET payload=?, updated_at=?, last_source=? WHERE account_id=?",
                        (encoded, now, source, account_id)
                    )
                    updated += 1
        con.execute("""
            INSERT INTO import_log(imported_at,source,received,inserted,updated,unchanged,rejected,quality_json)
            VALUES(?,?,?,?,?,?,?,?)
        """, (now, source, int(quality.get("rows_received", len(df))), inserted, updated,
              unchanged, rejected, json.dumps(quality, ensure_ascii=False)))
        con.commit()
    finally:
        con.close()
    return {
        "source": source, "received": int(quality.get("rows_received", len(df))),
        "inserted": inserted, "updated": updated, "unchanged": unchanged,
        "rejected": rejected, "total_accounts": len(get_accounts())
    }

def get_accounts():
    con = _connect()
    try:
        rows = con.execute("SELECT payload FROM accounts ORDER BY account_id").fetchall()
        if not rows:
            return pd.DataFrame(columns=EXPECTED_COLUMNS)
        return pd.DataFrame([json.loads(r["payload"]) for r in rows], columns=EXPECTED_COLUMNS)
    finally:
        con.close()

def get_import_log():
    con = _connect()
    try:
        rows = con.execute("""
            SELECT imported_at, source, received, inserted, updated, unchanged, rejected, quality_json
            FROM import_log ORDER BY id DESC LIMIT 20
        """).fetchall()
        output = []
        for r in rows:
            output.append({
                "imported_at": r["imported_at"],
                "source": r["source"],
                "received": r["received"],
                "inserted": r["inserted"],
                "updated": r["updated"],
                "unchanged": r["unchanged"],
                "rejected": r["rejected"]
            })
        return output
    finally:
        con.close()

def get_action_state(account_id, action_key):
    con = _connect()
    try:
        row = con.execute(
            "SELECT status,note,draft_override,updated_at FROM action_state WHERE account_id=? AND action_key=?",
            (str(account_id), str(action_key))
        ).fetchone()
        if row is None:
            return {"status": "Pending", "note": "", "draft_override": None, "updated_at": None}
        return dict(row)
    finally:
        con.close()

def save_action_state(account_id, action_key, status, note="", draft_override=None):
    now = datetime.now(timezone.utc).isoformat()
    con = _connect()
    try:
        with con:
            con.execute("""
                INSERT INTO action_state(account_id,action_key,status,note,updated_at,draft_override)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(account_id,action_key) DO UPDATE SET
                    status=excluded.status, note=excluded.note,
                    draft_override=excluded.draft_override, updated_at=excluded.updated_at
            """, (str(account_id), str(action_key), str(status), str(note), now, draft_override))
    finally:
        con.close()
