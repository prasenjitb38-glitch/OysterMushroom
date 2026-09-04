from database import get_connection


def setting(key, default=""):
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def mushroom_stock(conn=None, exclude_sale_id=None):
    own = conn is None
    conn = conn or get_connection()
    opening = float(setting("opening_mushroom_stock", "0") or 0)
    adjustments = conn.execute(
        "SELECT COALESCE(SUM(quantity_kg),0) FROM stock_transactions"
    ).fetchone()[0]
    saleable = conn.execute(
        "SELECT COALESCE(SUM(quantity_kg-wastage_kg),0) FROM harvests"
    ).fetchone()[0]
    if exclude_sale_id is None:
        sold = conn.execute("SELECT COALESCE(SUM(quantity_kg),0) FROM sales").fetchone()[0]
    else:
        sold = conn.execute(
            "SELECT COALESCE(SUM(quantity_kg),0) FROM sales WHERE id!=?", (exclude_sale_id,)
        ).fetchone()[0]
    if own:
        conn.close()
    return opening + adjustments + saleable - sold


def customer_outstanding(customer_id=None, conn=None):
    own = conn is None; conn = conn or get_connection()
    where = " WHERE id=?" if customer_id is not None else ""
    params = (customer_id,) if customer_id is not None else ()
    opening = conn.execute("SELECT COALESCE(SUM(opening_due),0) FROM customers"+where, params).fetchone()[0]
    child_where = " WHERE customer_id=?" if customer_id is not None else ""
    due = conn.execute("SELECT COALESCE(SUM(total_amount-paid_amount),0) FROM sales"+child_where, params).fetchone()[0]
    payments = conn.execute("SELECT COALESCE(SUM(amount),0) FROM customer_payments"+child_where, params).fetchone()[0]
    if own: conn.close()
    return opening + due - payments


def supplier_outstanding(supplier_id=None, conn=None):
    own = conn is None; conn = conn or get_connection()
    clause = " WHERE id=?" if supplier_id is not None else ""
    params = (supplier_id,) if supplier_id is not None else ()
    opening = conn.execute("SELECT COALESCE(SUM(opening_due),0) FROM suppliers"+clause, params).fetchone()[0]
    p_clause = " WHERE supplier_id=?" if supplier_id is not None else ""
    purchases = conn.execute("SELECT COALESCE(SUM(total_amount-paid_amount),0) FROM purchases"+p_clause, params).fetchone()[0]
    payments = conn.execute("SELECT COALESCE(SUM(amount),0) FROM supplier_payments"+p_clause, params).fetchone()[0]
    if own: conn.close()
    return opening + purchases - payments


def labour_due(conn=None):
    own = conn is None; conn = conn or get_connection()
    due = conn.execute("SELECT COALESCE(SUM(amount-paid),0) FROM labour").fetchone()[0]
    paid = conn.execute("SELECT COALESCE(SUM(amount),0) FROM labour_payments").fetchone()[0]
    if own: conn.close()
    return due - paid


def cash_balance(mode="All", conn=None):
    own = conn is None; conn = conn or get_connection()
    opening = float(setting("opening_cash", "0") or 0) + float(setting("opening_bank", "0") or 0)
    where = "" if mode == "All" else " WHERE payment_mode=?"
    params = () if mode == "All" else (mode,)
    debit, credit = conn.execute(
        "SELECT COALESCE(SUM(debit),0),COALESCE(SUM(credit),0) FROM cash_ledger" + where, params
    ).fetchone()
    if own: conn.close()
    return opening + credit - debit


def raw_material_stock(material_id, conn=None):
    own = conn is None; conn = conn or get_connection()
    row = conn.execute("SELECT item,opening_stock FROM raw_materials WHERE id=?",(material_id,)).fetchone()
    if not row: result=0
    else:
        purchased=conn.execute("SELECT COALESCE(SUM(quantity),0) FROM purchases WHERE item=?",(row[0],)).fetchone()[0]
        used=conn.execute("SELECT COALESCE(SUM(quantity),0) FROM material_usage WHERE material_id=?",(material_id,)).fetchone()[0]
        result=(row[1] or 0)+purchased-used
    if own: conn.close()
    return result


def batch_cost_rows():
    expected_rate = float(setting("expected_rate", "0") or 0)
    with get_connection() as conn:
        batches = conn.execute("SELECT batch_no,production_date,bag_count,expected_yield FROM batches ORDER BY id DESC").fetchall()
        result=[]
        for batch,date,bags,expected_yield in batches:
            production,wastage,saleable=conn.execute("SELECT COALESCE(SUM(production_kg),0),COALESCE(SUM(wastage_kg),0),COALESCE(SUM(saleable_kg),0) FROM daily_production WHERE batch_no=?",(batch,)).fetchone()
            purchases=conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM purchases WHERE batch_no=?",(batch,)).fetchone()[0]
            expenses=conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE batch_no=?",(batch,)).fetchone()[0]
            labour=conn.execute("SELECT COALESCE(SUM(amount),0) FROM labour WHERE batch_no=?",(batch,)).fetchone()[0]
            total=purchases+expenses+labour; expected_sales=(expected_yield or 0)*expected_rate
            result.append((batch,date,bags,production,wastage,saleable,total,total/bags if bags else 0,total/saleable if saleable else 0,expected_sales,expected_sales-total))
    return result


def validate_sale(qty, rate, discount, paid, available):
    total = qty * rate - discount
    if qty <= 0 or rate <= 0 or discount < 0 or total < 0 or paid < 0 or paid > total:
        raise ValueError("Invalid sale values")
    if qty > available:
        raise OverflowError(f"Available stock: {available:.2f} Kg")
    return total


def generate_invoice_no():
    prefix = setting("invoice_prefix", "INV") or "INV"
    with get_connection() as conn:
        rows = conn.execute("SELECT invoice_no FROM sales ORDER BY id DESC").fetchall()
    largest = 0
    for (invoice,) in rows:
        try:
            largest = max(largest, int(invoice.split("-")[-1]))
        except (ValueError, AttributeError):
            continue
    return f"{prefix}-{largest + 1:05d}"


def pnl(start=None, end=None):
    sale_where=""; expense_where=""; params=()
    if start and end:
        sale_where=" WHERE sale_date BETWEEN ? AND ?"; expense_where=" WHERE expense_date BETWEEN ? AND ?"; params=(start,end)
    with get_connection() as conn:
        sales,sold=conn.execute("SELECT COALESCE(SUM(total_amount),0),COALESCE(SUM(quantity_kg),0) FROM sales"+sale_where,params).fetchone()
        operating=conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses"+expense_where,params).fetchone()[0]
        # COGS uses batch-linked purchases and labour only; expenses stay operating costs.
        cogs=conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM purchases WHERE COALESCE(batch_no,'')!=''").fetchone()[0]
        cogs+=conn.execute("SELECT COALESCE(SUM(amount),0) FROM labour WHERE COALESCE(batch_no,'')!=''").fetchone()[0]
    gross=sales-cogs; net=gross-operating
    return {"sales":sales,"sold_kg":sold,"cogs":cogs,"gross":gross,"expenses":operating,"net":net,"margin":net/sales*100 if sales else 0,"per_kg":net/sold if sold else 0}
