"""Web-safe transactional service for owner's capital and drawings."""
from datetime import datetime

from database import get_connection

KINDS = ("OPENING", "INTRODUCED", "DRAWING")
LEDGER_TYPES = {
    "OPENING": "OPENING CAPITAL",
    "INTRODUCED": "CAPITAL INTRODUCED",
    "DRAWING": "DRAWINGS",
}
SOURCE_PREFIXES = {
    "OPENING": "owner_capital_opening",
    "INTRODUCED": "owner_capital_introduced",
    "DRAWING": "owner_capital_drawing",
}


def _validate(data):
    kind = str(data.get("kind", "")).strip().upper()
    if kind not in KINDS:
        raise ValueError("Choose a valid capital transaction type.")
    value_date = str(data.get("date", "")).strip()
    try:
        datetime.strptime(value_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("Date must use YYYY-MM-DD format.")
    try:
        cash = float(data.get("cash_amount", 0) or 0)
        bank = float(data.get("bank_amount", 0) or 0)
    except (TypeError, ValueError):
        raise ValueError("Cash and bank amounts must be valid numbers.")
    if cash < 0 or bank < 0:
        raise ValueError("Cash and bank amounts cannot be negative.")
    if cash + bank <= 0:
        raise ValueError("Enter a cash or bank amount greater than zero.")
    return (
        value_date, kind, cash, bank,
        str(data.get("reference", "")).strip(),
        str(data.get("notes", "")).strip(),
    )


def _delete_ledgers(conn, entry_id):
    conn.execute(
        """DELETE FROM cash_ledger WHERE source_id=? AND source_table IN (
        'owner_capital_opening_cash','owner_capital_opening_bank',
        'owner_capital_introduced_cash','owner_capital_introduced_bank',
        'owner_capital_drawing_cash','owner_capital_drawing_bank')""",
        (entry_id,),
    )


def _post_ledgers(conn, entry_id, values):
    value_date, kind, cash, bank, reference, notes = values
    ledger_type = LEDGER_TYPES[kind]
    prefix = SOURCE_PREFIXES[kind]
    inflow = kind != "DRAWING"
    for component, mode, amount in (("cash", "Cash", cash), ("bank", "Bank", bank)):
        if amount:
            conn.execute(
                """INSERT INTO cash_ledger
                (transaction_date,transaction_type,reference,payment_mode,debit,credit,notes,source_table,source_id)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (value_date, ledger_type, reference, mode,
                 0 if inflow else amount, amount if inflow else 0, notes,
                 f"{prefix}_{component}", entry_id),
            )


def _sync_opening_settings(conn, kind, cash=0, bank=0):
    if kind == "OPENING":
        conn.executemany(
            """INSERT INTO settings(key,value) VALUES(?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (("opening_cash", str(cash)), ("opening_bank", str(bank))),
        )


def save_capital(data, entry_id=None):
    values = _validate(data)
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        old = None
        if entry_id is not None:
            old = conn.execute(
                "SELECT kind FROM owner_capital WHERE id=?", (entry_id,)
            ).fetchone()
            if not old:
                raise ValueError("Capital entry was not found.")
        if values[1] == "OPENING":
            duplicate = conn.execute(
                "SELECT id FROM owner_capital WHERE kind='OPENING' AND id<>?",
                (entry_id or 0,),
            ).fetchone()
            if duplicate:
                raise ValueError("Opening capital has already been set up.")
        if entry_id is None:
            entry_id = conn.execute(
                """INSERT INTO owner_capital
                (date,kind,cash_amount,bank_amount,reference,notes)
                VALUES(?,?,?,?,?,?)""", values
            ).lastrowid
        else:
            _delete_ledgers(conn, entry_id)
            conn.execute(
                """UPDATE owner_capital SET date=?,kind=?,cash_amount=?,bank_amount=?,
                reference=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                values + (entry_id,),
            )
            if old[0] == "OPENING" and values[1] != "OPENING":
                _sync_opening_settings(conn, "OPENING", 0, 0)
        _post_ledgers(conn, entry_id, values)
        _sync_opening_settings(conn, values[1], values[2], values[3])
        conn.commit()
        return entry_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_capital(entry_id):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT kind FROM owner_capital WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            raise ValueError("Capital entry was not found.")
        _delete_ledgers(conn, entry_id)
        conn.execute("DELETE FROM owner_capital WHERE id=?", (entry_id,))
        _sync_opening_settings(conn, row[0], 0, 0)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_capital(entry_id):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id,date,kind,cash_amount,bank_amount,reference,notes
            FROM owner_capital WHERE id=?""", (entry_id,)
        ).fetchone()
    return row


def capital_register(start=None, end=None, conn=None):
    own = conn is None
    conn = conn or get_connection()
    clauses, params = [], []
    if start:
        clauses.append("date>=?"); params.append(start)
    if end:
        clauses.append("date<=?"); params.append(end)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        """SELECT id,date,kind,COALESCE(reference,''),cash_amount,bank_amount,
        cash_amount+bank_amount,COALESCE(notes,'') FROM owner_capital"""
        + where + " ORDER BY date DESC,id DESC", params
    ).fetchall()
    if own:
        conn.close()
    return rows


def capital_summary(conn=None):
    own = conn is None
    conn = conn or get_connection()
    totals = dict(conn.execute(
        """SELECT kind,COALESCE(SUM(cash_amount+bank_amount),0)
        FROM owner_capital GROUP BY kind"""
    ).fetchall())
    result = {
        "opening": float(totals.get("OPENING", 0)),
        "introduced": float(totals.get("INTRODUCED", 0)),
        "drawings": float(totals.get("DRAWING", 0)),
    }
    result["closing"] = result["opening"] + result["introduced"] - result["drawings"]
    if own:
        conn.close()
    return result
