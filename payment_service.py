from database import get_connection
from events import publish
from services import (
    customer_outstanding,
    enforce_desktop,
    post_ledger,
    supplier_outstanding,
)


PAYMENT_SOURCES = {
    "CUSTOMER PAYMENT": ("customer_payments", "customer_id"),
    "SUPPLIER PAYMENT": ("supplier_payments", "supplier_id"),
    "LABOUR PAYMENT": ("labour_payments", "labour_id"),
}
MANUAL_PAYMENT_TYPES = {"OTHER PAYMENT", "OTHER INCOME"}


def _validate_payment(payment_type, amount, mode):
    amount = float(amount)
    if amount <= 0:
        raise ValueError("Amount must be positive")
    if payment_type not in PAYMENT_SOURCES and payment_type not in MANUAL_PAYMENT_TYPES:
        raise ValueError("Unsupported payment type")
    if not (mode or "").strip() or (mode or "").strip().lower() == "credit":
        raise ValueError("Payment mode must post to Cash or Bank ledger")
    return amount


def _payment_limit(conn, payment_type, party_id):
    if payment_type == "CUSTOMER PAYMENT":
        if not conn.execute("SELECT 1 FROM customers WHERE id=?", (party_id,)).fetchone():
            raise ValueError("Customer not found")
        return customer_outstanding(party_id, conn)
    if payment_type == "SUPPLIER PAYMENT":
        if not conn.execute("SELECT 1 FROM suppliers WHERE id=?", (party_id,)).fetchone():
            raise ValueError("Supplier not found")
        return supplier_outstanding(party_id, conn)
    if payment_type == "LABOUR PAYMENT":
        row = conn.execute(
            """SELECT amount-paid-COALESCE(
                   (SELECT SUM(amount) FROM labour_payments WHERE labour_id=labour.id),0)
               FROM labour WHERE id=?""",
            (party_id,),
        ).fetchone()
        if not row:
            raise ValueError("Labour entry not found")
        return float(row[0] or 0)
    return None


def _check_duplicate_reference(conn, table, party_column, party_id, reference):
    if reference and conn.execute(
        f"""SELECT 1 FROM {table}
            WHERE {party_column}=? AND TRIM(reference_no)=? COLLATE NOCASE LIMIT 1""",
        (party_id, reference),
    ).fetchone():
        raise ValueError("A payment with this reference already exists for this party")


def _insert_manual_ledger(conn, payment_date, payment_type, amount, mode, reference, notes):
    inflow = payment_type == "OTHER INCOME"
    ledger_id = conn.execute(
        """INSERT INTO cash_ledger
           (transaction_date,transaction_type,reference,payment_mode,debit,credit,notes)
           VALUES(?,?,?,?,?,?,?)""",
        (
            payment_date, payment_type, reference, mode,
            0 if inflow else amount, amount if inflow else 0, notes,
        ),
    ).lastrowid
    conn.execute(
        """UPDATE cash_ledger SET source_table='manual_payment',source_id=?
           WHERE id=?""",
        (ledger_id, ledger_id),
    )
    return ledger_id


def record_payment(payment_date, payment_type, party_id, amount, mode, reference="", notes=""):
    enforce_desktop("payments.create")
    amount = _validate_payment(payment_type, amount, mode)
    reference = (reference or "").strip()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if payment_type in PAYMENT_SOURCES:
            table, party_column = PAYMENT_SOURCES[payment_type]
            allowed = _payment_limit(conn, payment_type, party_id)
            if amount > allowed + 1e-9:
                raise ValueError("Payment exceeds outstanding due")
            _check_duplicate_reference(conn, table, party_column, party_id, reference)
            source_table = table
            source_id = conn.execute(
                f"""INSERT INTO {table}
                    (payment_date,{party_column},amount,payment_mode,reference_no,notes)
                    VALUES(?,?,?,?,?,?)""",
                (payment_date, party_id, amount, mode, reference, notes),
            ).lastrowid
            ledger_id = post_ledger(
                conn, table, source_id, payment_date, payment_type, mode, amount,
                payment_type == "CUSTOMER PAYMENT", reference, notes,
            )
            if ledger_id is None:
                raise ValueError("Payment mode must post to Cash or Bank ledger")
        else:
            ledger_id = _insert_manual_ledger(
                conn, payment_date, payment_type, amount, mode, reference, notes
            )
    publish("payment_changed")
    return ledger_id


def delete_payment(ledger_id):
    enforce_desktop("payments.delete")
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT source_table,source_id FROM cash_ledger WHERE id=?", (ledger_id,)
        ).fetchone()
        if not row:
            return False
        valid_tables = {source[0] for source in PAYMENT_SOURCES.values()}
        if row[0] not in valid_tables | {"manual_payment"} or row[1] is None:
            raise ValueError("Ledger entry is not a linked payment")
        if row[0] in valid_tables:
            conn.execute(f"DELETE FROM {row[0]} WHERE id=?", (row[1],))
        conn.execute("DELETE FROM cash_ledger WHERE id=?", (ledger_id,))
    publish("payment_changed")
    return True


def update_payment(ledger_id, payment_date, payment_type, party_id, amount, mode, reference="", notes=""):
    enforce_desktop("payments.edit")
    amount = _validate_payment(payment_type, amount, mode)
    reference = (reference or "").strip()

    valid_tables = {source[0] for source in PAYMENT_SOURCES.values()}
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT source_table,source_id FROM cash_ledger WHERE id=?", (ledger_id,)
        ).fetchone()
        if not old or old[0] not in valid_tables | {"manual_payment"} or old[1] is None:
            raise ValueError("Payment not found")
        old_payment = None
        if old[0] in valid_tables:
            old_party_column = next(
                column for source_table, column in PAYMENT_SOURCES.values()
                if source_table == old[0]
            )
            old_payment = conn.execute(
                f"SELECT {old_party_column},amount FROM {old[0]} WHERE id=?", (old[1],)
            ).fetchone()
            if not old_payment:
                raise ValueError("Linked payment not found")
            conn.execute(f"DELETE FROM {old[0]} WHERE id=?", (old[1],))

        source_table = "manual_payment"
        source_id = ledger_id
        if payment_type in PAYMENT_SOURCES:
            table, party_column = PAYMENT_SOURCES[payment_type]
            allowed = _payment_limit(conn, payment_type, party_id)
            if old[0] == table and old_payment and old_payment[0] == party_id:
                allowed = max(allowed, float(old_payment[1] or 0))
            if amount > allowed + 1e-9:
                raise ValueError("Payment exceeds outstanding due")
            _check_duplicate_reference(conn, table, party_column, party_id, reference)
            source_table = table
            source_id = conn.execute(
                f"""INSERT INTO {table}
                    (payment_date,{party_column},amount,payment_mode,reference_no,notes)
                    VALUES(?,?,?,?,?,?)""",
                (payment_date, party_id, amount, mode, reference, notes),
            ).lastrowid
        inflow = payment_type in ("CUSTOMER PAYMENT", "OTHER INCOME")
        conn.execute(
            """UPDATE cash_ledger
               SET transaction_date=?,transaction_type=?,reference=?,payment_mode=?,
                   debit=?,credit=?,notes=?,source_table=?,source_id=?
               WHERE id=?""",
            (
                payment_date, payment_type, reference, mode,
                0 if inflow else amount, amount if inflow else 0,
                notes, source_table, source_id, ledger_id,
            ),
        )
    publish("payment_changed")
    return ledger_id
