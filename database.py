import os
import sqlite3
import hashlib
import secrets


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FOLDER = os.path.join(BASE_DIR, "database")
DB_FILE = os.path.join(DB_FOLDER, "mushroom.db")


class DatabaseConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_connection():
    os.makedirs(DB_FOLDER, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, factory=DatabaseConnection)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
    _add_column(cursor, "expenses", "notes TEXT")
    _add_column(cursor, "cash_ledger", "source_table TEXT")
    _add_column(cursor, "cash_ledger", "source_id INTEGER")

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
    """)

    conn.commit()
    conn.close()
    print("Database created successfully!")


if __name__ == "__main__":
    create_database()
