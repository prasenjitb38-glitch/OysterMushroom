import os
import sqlite3
import hashlib
import secrets
import threading


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_database_paths(environment=None, base_dir=BASE_DIR):
    environment=environment if environment is not None else os.environ
    configured=(environment.get("MUSHROOM_DATA_DIR") or "").strip()
    production=(environment.get("APP_ENV") or environment.get("FLASK_ENV") or "development").lower()=="production"
    folder=os.path.abspath(configured or ("/var/data" if production else os.path.join(base_dir,"database")))
    return folder,os.path.join(folder,"mushroom.db")

DB_FOLDER,DB_FILE=resolve_database_paths()
DB_MAINTENANCE_LOCK=threading.RLock()


class DatabaseConnection(sqlite3.Connection):
    _maintenance_lock_held = False

    def close(self):
        if self._maintenance_lock_held:
            self._maintenance_lock_held = False
            try:
                super().close()
            finally:
                DB_MAINTENANCE_LOCK.release()
        else:
            super().close()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_connection():
    DB_MAINTENANCE_LOCK.acquire()
    try:
        os.makedirs(DB_FOLDER, exist_ok=True)
        conn = sqlite3.connect(DB_FILE, factory=DatabaseConnection, timeout=15)
        conn._maintenance_lock_held = True
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn
    except Exception:
        DB_MAINTENANCE_LOCK.release()
        raise


def _add_column(cursor, table, definition):
    column = definition.split()[0]
    columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    try:
        salt, expected = stored.split("$", 1)
        actual = hash_password(password, salt).split("$", 1)[1]
        return secrets.compare_digest(actual, expected)
    except (ValueError, AttributeError):
        return False


def authenticate(username, password):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id,password_hash,role,active,full_name,must_change_password FROM users WHERE username=?",
            (username,),
        ).fetchone()
    return row if row and row[3] and verify_password(password, row[1]) else None


def validate_password(password):
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    if password.isspace():
        raise ValueError("Password cannot be blank")
    return True


def change_password(user_id, current_password, new_password, admin_reset=False):
    validate_password(new_password)
    with get_connection() as conn:
        row=conn.execute("SELECT password_hash FROM users WHERE id=?",(user_id,)).fetchone()
        if not row or (not admin_reset and not verify_password(current_password,row[0])):raise ValueError("Current password is incorrect")
        conn.execute("UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?",(hash_password(new_password),user_id))


def set_user_active(user_id, active):
    with get_connection() as conn:
        row=conn.execute("SELECT role,active FROM users WHERE id=?",(user_id,)).fetchone()
        if not row:raise ValueError("User not found")
        if row[0].upper()=="ADMIN" and row[1] and not active:
            count=conn.execute("SELECT COUNT(*) FROM users WHERE role='ADMIN' AND active=1").fetchone()[0]
            if count<=1:raise ValueError("The last active Admin cannot be disabled")
        conn.execute("UPDATE users SET active=? WHERE id=?",(1 if active else 0,user_id))

def admin_reset_password(admin_id,user_id,new_password):
    validate_password(new_password)
    with get_connection() as conn:
        admin=conn.execute("SELECT role,active FROM users WHERE id=?",(admin_id,)).fetchone()
        if not admin or admin[0]!="ADMIN" or not admin[1]:raise PermissionError("Admin permission required")
        if not conn.execute("SELECT 1 FROM users WHERE id=?",(user_id,)).fetchone():raise ValueError("User not found")
        conn.execute("UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?",(hash_password(new_password),user_id))


def create_database():
    conn = get_connection()
    cursor = conn.cursor()

    # Batch
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_no TEXT UNIQUE NOT NULL,
            production_date TEXT NOT NULL,
            straw_qty REAL DEFAULT 0,
            spawn_qty REAL DEFAULT 0,
            bag_count INTEGER DEFAULT 0,
            expected_yield REAL DEFAULT 0,
            expected_harvest_date TEXT,
            status TEXT DEFAULT 'Preparing',
            notes TEXT
        )
    """)

    # Daily Production
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_production (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            production_date TEXT NOT NULL,
            batch_no TEXT NOT NULL,
            bags INTEGER DEFAULT 0,
            production_kg REAL DEFAULT 0,
            wastage_kg REAL DEFAULT 0,
            saleable_kg REAL DEFAULT 0,
            notes TEXT
        )
    """)

    # Harvest
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS harvests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            harvest_date TEXT NOT NULL,
            batch_no TEXT NOT NULL,
            flush_no INTEGER DEFAULT 1,
            quantity_kg REAL DEFAULT 0,
            wastage_kg REAL DEFAULT 0,
            grade TEXT,
            notes TEXT
        )
    """)

    # Expenses
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_date TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            amount REAL DEFAULT 0,
            payment_mode TEXT,
            batch_no TEXT
        )
    """)

    # Customers
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT,
            address TEXT,
            notes TEXT
        )
    """)

    # Sales
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT UNIQUE NOT NULL,
            sale_date TEXT NOT NULL,
            customer_id INTEGER,
            quantity_kg REAL DEFAULT 0,
            rate_per_kg REAL DEFAULT 0,
            discount REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            payment_mode TEXT,
            notes TEXT
        )
    """)

    # Raw Material Purchases
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_date TEXT NOT NULL,
            supplier TEXT,
            item TEXT NOT NULL,
            quantity REAL DEFAULT 0,
            unit TEXT,
            rate REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            paid_amount REAL DEFAULT 0,
            due_amount REAL DEFAULT 0,
            notes TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_date TEXT NOT NULL,
            transaction_type TEXT NOT NULL,
            batch_no TEXT,
            quantity_kg REAL DEFAULT 0,
            reference_id INTEGER,
            notes TEXT
        )
    """)

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT NOT NULL DEFAULT 'STAFF',
            active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT,
            address TEXT,
            email TEXT,
            notes TEXT,
            opening_due REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS raw_materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT UNIQUE NOT NULL,
            unit TEXT NOT NULL DEFAULT 'Kg',
            opening_stock REAL DEFAULT 0,
            reorder_level REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS material_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usage_date TEXT NOT NULL,
            material_id INTEGER NOT NULL,
            batch_no TEXT,
            quantity REAL NOT NULL DEFAULT 0,
            notes TEXT,
            FOREIGN KEY(material_id) REFERENCES raw_materials(id)
        );
        CREATE TABLE IF NOT EXISTS material_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adjustment_date TEXT NOT NULL,
            material_id INTEGER NOT NULL,
            adjustment_type TEXT NOT NULL CHECK(adjustment_type IN ('IN','OUT')),
            quantity REAL NOT NULL CHECK(quantity > 0),
            batch_id INTEGER,
            notes TEXT,
            FOREIGN KEY(material_id) REFERENCES raw_materials(id) ON DELETE RESTRICT,
            FOREIGN KEY(batch_id) REFERENCES batches(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS labour (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_name TEXT NOT NULL,
            work_date TEXT NOT NULL,
            work_type TEXT,
            batch_no TEXT,
            days REAL DEFAULT 0,
            hours REAL DEFAULT 0,
            rate REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            paid REAL DEFAULT 0,
            payment_mode TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS customer_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_date TEXT NOT NULL,
            customer_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            payment_mode TEXT,
            reference_no TEXT,
            notes TEXT,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
        CREATE TABLE IF NOT EXISTS supplier_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_date TEXT NOT NULL,
            supplier_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            payment_mode TEXT,
            reference_no TEXT,
            notes TEXT,
            FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
        );
        CREATE TABLE IF NOT EXISTS labour_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_date TEXT NOT NULL,
            labour_id INTEGER NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            payment_mode TEXT,
            reference_no TEXT,
            notes TEXT,
            FOREIGN KEY(labour_id) REFERENCES labour(id)
        );
        CREATE TABLE IF NOT EXISTS cash_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_date TEXT NOT NULL,
            transaction_type TEXT NOT NULL,
            reference TEXT,
            payment_mode TEXT,
            debit REAL DEFAULT 0,
            credit REAL DEFAULT 0,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT DEFAULT CURRENT_TIMESTAMP,
            username TEXT,
            action TEXT NOT NULL,
            table_name TEXT,
            record_id INTEGER,
            details TEXT
        );
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            description TEXT DEFAULT 'Oyster Mushroom',
            batch_no TEXT,
            quantity_kg REAL DEFAULT 0,
            rate_per_kg REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE
        );
    """)

    for definition in ("email TEXT", "opening_due REAL DEFAULT 0"):
        _add_column(cursor, "customers", definition)
    for definition in (
        "purchase_invoice TEXT", "supplier_id INTEGER", "batch_no TEXT",
        "payment_mode TEXT"
    ):
        _add_column(cursor, "purchases", definition)
    _add_column(cursor, "sales", "batch_no TEXT")
    _add_column(cursor, "sales", "batch_id INTEGER")
    _add_column(cursor, "daily_production", "batch_id INTEGER")
    _add_column(cursor, "harvests", "batch_id INTEGER")
    _add_column(cursor, "expenses", "batch_id INTEGER")
    _add_column(cursor, "labour", "batch_id INTEGER")
    _add_column(cursor, "purchases", "batch_id INTEGER")
    _add_column(cursor, "purchases", "material_id INTEGER")
    _add_column(cursor, "purchases", "cash_paid REAL DEFAULT 0")
    _add_column(cursor, "purchases", "bank_paid REAL DEFAULT 0")
    _add_column(cursor, "material_usage", "batch_id INTEGER")
    _add_column(cursor, "batches", "straw_type TEXT")
    _add_column(cursor, "batches", "bag_size REAL DEFAULT 0")
    _add_column(cursor, "batches", "room_rack TEXT")
    _add_column(cursor, "daily_production", "room_rack TEXT")
    _add_column(cursor, "expenses", "notes TEXT")
    _add_column(cursor, "cash_ledger", "source_table TEXT")
    _add_column(cursor, "cash_ledger", "source_id INTEGER")

    # Backfill relational keys without invalidating legacy/unallocated records.
    for table in ("sales", "daily_production", "harvests", "expenses", "labour", "purchases", "material_usage"):
        cursor.execute(f"""UPDATE {table} SET batch_id=(SELECT id FROM batches b
            WHERE b.batch_no={table}.batch_no) WHERE batch_id IS NULL AND COALESCE(batch_no,'')!=''""")
    cursor.execute("""UPDATE purchases SET material_id=(SELECT id FROM raw_materials r
        WHERE r.item=purchases.item) WHERE material_id IS NULL""")
    cursor.execute("""UPDATE purchases SET cash_paid=paid_amount
        WHERE COALESCE(cash_paid,0)=0 AND COALESCE(bank_paid,0)=0 AND LOWER(COALESCE(payment_mode,''))='cash'""")
    cursor.execute("""UPDATE purchases SET bank_paid=paid_amount
        WHERE COALESCE(cash_paid,0)=0 AND COALESCE(bank_paid,0)=0 AND LOWER(COALESCE(payment_mode,'')) IN ('bank','upi','online')""")

    defaults = {
        "business_name": "Oyster Mushroom Business",
        "address": "", "mobile": "", "email": "", "gstin": "",
        "logo": "", "invoice_prefix": "INV", "opening_cash": "0",
        "opening_bank": "0", "opening_mushroom_stock": "0",
        "default_payment_mode": "Cash", "backup_folder": DB_FOLDER,
        "units": "Kg,Gram,Bag,Piece,Litre", "expected_rate": "0",
    }
    cursor.executemany(
        "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", defaults.items()
    )
    cursor.execute("""
        INSERT OR IGNORE INTO users(username, password_hash, full_name, role, active)
        VALUES ('admin', ?, 'Administrator', 'ADMIN', 1)
    """, (hash_password("admin"),))
    cursor.executemany("""
        INSERT OR IGNORE INTO raw_materials(item, unit, opening_stock, reorder_level)
        VALUES (?, ?, 0, 0)
    """, [(item, unit) for item, unit in (
        ("Paddy Straw", "Kg"), ("Wheat Straw", "Kg"), ("Spawn", "Kg"),
        ("Polybag", "Piece"), ("Rubber Band", "Piece"), ("Lime", "Kg"),
        ("Disinfectant", "Litre"), ("Packaging Material", "Piece"), ("Other", "Unit")
    )])

    cursor.executescript("""
        CREATE INDEX IF NOT EXISTS idx_batches_date ON batches(production_date);
        CREATE INDEX IF NOT EXISTS idx_daily_production_date ON daily_production(production_date);
        CREATE INDEX IF NOT EXISTS idx_daily_production_batch ON daily_production(batch_no);
        CREATE INDEX IF NOT EXISTS idx_harvest_date ON harvests(harvest_date);
        CREATE INDEX IF NOT EXISTS idx_harvest_batch ON harvests(batch_no);
        CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date);
        CREATE INDEX IF NOT EXISTS idx_sales_customer ON sales(customer_id);
        CREATE INDEX IF NOT EXISTS idx_sales_batch ON sales(batch_no);
        CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
        CREATE INDEX IF NOT EXISTS idx_purchases_date ON purchases(purchase_date);
        CREATE INDEX IF NOT EXISTS idx_purchases_supplier ON purchases(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_labour_date ON labour(work_date);
        CREATE INDEX IF NOT EXISTS idx_labour_batch ON labour(batch_no);
        CREATE INDEX IF NOT EXISTS idx_cash_ledger_date ON cash_ledger(transaction_date);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_ledger_source
        ON cash_ledger(source_table, source_id)
        WHERE source_table IS NOT NULL AND source_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_sales_batch_id ON sales(batch_id);
        CREATE INDEX IF NOT EXISTS idx_usage_material ON material_usage(material_id);
        CREATE INDEX IF NOT EXISTS idx_adjustment_material ON material_adjustments(material_id);
        CREATE INDEX IF NOT EXISTS idx_customer_payments_party ON customer_payments(customer_id);
        CREATE INDEX IF NOT EXISTS idx_supplier_payments_party ON supplier_payments(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_labour_payments_party ON labour_payments(labour_id);

        DROP TRIGGER IF EXISTS protect_ledger_update;
        DROP TRIGGER IF EXISTS protect_ledger_delete;
        CREATE TRIGGER IF NOT EXISTS sales_customer_valid_insert BEFORE INSERT ON sales
        WHEN NEW.customer_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM customers WHERE id=NEW.customer_id)
        BEGIN SELECT RAISE(ABORT,'invalid customer'); END;
        CREATE TRIGGER IF NOT EXISTS sales_batch_valid_insert BEFORE INSERT ON sales
        WHEN NEW.batch_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM batches WHERE id=NEW.batch_id)
        BEGIN SELECT RAISE(ABORT,'invalid batch'); END;
        CREATE TRIGGER IF NOT EXISTS purchases_supplier_valid_insert BEFORE INSERT ON purchases
        WHEN NEW.supplier_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM suppliers WHERE id=NEW.supplier_id)
        BEGIN SELECT RAISE(ABORT,'invalid supplier'); END;
        CREATE TRIGGER IF NOT EXISTS purchases_material_valid_insert BEFORE INSERT ON purchases
        WHEN NEW.material_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM raw_materials WHERE id=NEW.material_id)
        BEGIN SELECT RAISE(ABORT,'invalid material'); END;
        CREATE TRIGGER IF NOT EXISTS protect_customer_delete BEFORE DELETE ON customers
        WHEN EXISTS(SELECT 1 FROM sales WHERE customer_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'customer has sales'); END;
        CREATE TRIGGER IF NOT EXISTS protect_supplier_delete BEFORE DELETE ON suppliers
        WHEN EXISTS(SELECT 1 FROM purchases WHERE supplier_id=OLD.id)
        BEGIN SELECT RAISE(ABORT,'supplier has purchases'); END;
    """)

    conn.commit()
    conn.close()
    print("Database created successfully!")


if __name__ == "__main__":
    create_database()
