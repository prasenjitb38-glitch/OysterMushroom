import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import database


REQUIRED_SCHEMA = {
    "settings": {"key", "value"},
    "users": {"id", "username", "password_hash", "role"},
    "batches": {"id", "batch_no", "production_date"},
    "sales": {"id", "invoice_no", "sale_date", "total_amount", "paid_amount"},
    "customers": {"id", "name"},
    "purchases": {"id", "purchase_date", "total_amount"},
    "expenses": {"id", "expense_date", "amount"},
    "cash_ledger": {"id", "transaction_date", "debit", "credit"},
}


def _readonly_uri(path):
    return Path(path).resolve().as_uri() + "?mode=ro"


def validate_backup(path):
    if not path or not os.path.isfile(path) or os.path.getsize(path) < 100:
        raise ValueError("Selected backup is empty or missing")
    with open(path, "rb") as source:
        if source.read(16) != b"SQLite format 3\x00":
            raise ValueError("Selected file is not a SQLite database")
    with closing(sqlite3.connect(_readonly_uri(path), uri=True)) as check:
        check.execute("PRAGMA foreign_keys=ON")
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Selected backup is damaged")
        if check.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Selected backup has invalid linked records")
        actual = {
            row[0]
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not REQUIRED_SCHEMA.keys() <= actual:
            raise ValueError("Selected file is not an Oyster Mushroom backup")
        for table, required in REQUIRED_SCHEMA.items():
            columns = {
                row[1] for row in check.execute(f"PRAGMA table_info({table})")
            }
            if not required <= columns:
                raise ValueError(
                    "Selected file has an incompatible Oyster Mushroom schema"
                )
    return True


def backup_database(source, destination):
    source = os.path.abspath(source)
    destination = os.path.abspath(destination)
    if source == destination:
        raise ValueError("Backup source and destination must be different")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with database.DB_MAINTENANCE_LOCK:
        with closing(sqlite3.connect(_readonly_uri(source), uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
    return validate_backup(destination)


def restore_database(backup, target):
    validate_backup(backup)
    target = os.path.abspath(target)
    folder = os.path.dirname(target)
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safety = os.path.join(folder, f".mushroom-safety-{stamp}.db")
    with database.DB_MAINTENANCE_LOCK:
        backup_database(target, safety)
        try:
            with closing(sqlite3.connect(_readonly_uri(backup), uri=True)) as src:
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
            if target == os.path.abspath(database.DB_FILE):
                database.create_database()
            validate_backup(target)
        except Exception:
            with closing(sqlite3.connect(_readonly_uri(safety), uri=True)) as src:
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
            if target == os.path.abspath(database.DB_FILE):
                try:
                    database.create_database()
                except Exception:
                    pass
            raise
    return safety
