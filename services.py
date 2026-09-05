from database import get_connection
from events import publish


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
    normalized = (mode or "All").strip().lower()
    if normalized == "cash": opening = float(setting("opening_cash", "0") or 0); modes=("Cash",)
    elif normalized in ("bank", "upi"): opening = float(setting("opening_bank", "0") or 0); modes=("Bank","UPI")
    else: opening = float(setting("opening_cash", "0") or 0)+float(setting("opening_bank", "0") or 0); modes=()
    where = "" if not modes else " WHERE payment_mode IN ("+",".join("?" for _ in modes)+")"
    params = modes
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
        purchased=conn.execute("SELECT COALESCE(SUM(quantity),0) FROM purchases WHERE material_id=? OR (material_id IS NULL AND item=?)",(material_id,row[0])).fetchone()[0]
        used=conn.execute("SELECT COALESCE(SUM(quantity),0) FROM material_usage WHERE material_id=?",(material_id,)).fetchone()[0]
        adj_in,adj_out=conn.execute("SELECT COALESCE(SUM(CASE WHEN adjustment_type='IN' THEN quantity END),0),COALESCE(SUM(CASE WHEN adjustment_type='OUT' THEN quantity END),0) FROM material_adjustments WHERE material_id=?",(material_id,)).fetchone()
        result=(row[1] or 0)+purchased+adj_in-used-adj_out
    if own: conn.close()
    return result


def batch_cost_rows():
    expected_rate = float(setting("expected_rate", "0") or 0)
    with get_connection() as conn:
        batches = conn.execute("SELECT batch_no,production_date,bag_count,expected_yield FROM batches ORDER BY id DESC").fetchall()
        result=[]
        for batch,date,bags,expected_yield in batches:
            production,wastage,saleable=conn.execute("SELECT COALESCE(SUM(production_kg),0),COALESCE(SUM(wastage_kg),0),COALESCE(SUM(saleable_kg),0) FROM daily_production WHERE batch_no=?",(batch,)).fetchone()
            usage_cost=conn.execute("""SELECT COALESCE(SUM(u.quantity*COALESCE((SELECT SUM(p.total_amount)/NULLIF(SUM(p.quantity),0) FROM purchases p WHERE p.material_id=u.material_id),0)),0) FROM material_usage u WHERE u.batch_id=(SELECT id FROM batches WHERE batch_no=?)""",(batch,)).fetchone()[0]
            purchases=conn.execute("""SELECT COALESCE(SUM(p.total_amount),0) FROM purchases p WHERE p.batch_no=? AND NOT EXISTS(SELECT 1 FROM material_usage u JOIN batches b ON b.id=u.batch_id WHERE b.batch_no=? AND u.material_id=p.material_id)""",(batch,batch)).fetchone()[0]+usage_cost
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
    sale_where=""; expense_where=""; purchase_where=" WHERE COALESCE(batch_no,'')!='' AND NOT EXISTS(SELECT 1 FROM material_usage u WHERE u.material_id=purchases.material_id)"; labour_where=" WHERE COALESCE(batch_no,'')!=''"; usage_where=""; params=()
    if start and end:
        sale_where=" WHERE sale_date BETWEEN ? AND ?"; expense_where=" WHERE expense_date BETWEEN ? AND ?"; purchase_where+=" AND purchase_date BETWEEN ? AND ?"; labour_where+=" AND work_date BETWEEN ? AND ?";usage_where=" WHERE u.usage_date BETWEEN ? AND ?"; params=(start,end)
    with get_connection() as conn:
        sales,sold=conn.execute("SELECT COALESCE(SUM(total_amount),0),COALESCE(SUM(quantity_kg),0) FROM sales"+sale_where,params).fetchone()
        operating=conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses"+expense_where,params).fetchone()[0]
        # COGS uses batch-linked purchases and labour only; expenses stay operating costs.
        cogs=conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM purchases"+purchase_where,params).fetchone()[0]
        cogs+=conn.execute("SELECT COALESCE(SUM(amount),0) FROM labour"+labour_where,params).fetchone()[0]
        cogs+=conn.execute("SELECT COALESCE(SUM(u.quantity*COALESCE((SELECT SUM(p.total_amount)/NULLIF(SUM(p.quantity),0) FROM purchases p WHERE p.material_id=u.material_id),0)),0) FROM material_usage u"+usage_where,params).fetchone()[0]
    gross=sales-cogs; net=gross-operating
    return {"sales":sales,"sold_kg":sold,"cogs":cogs,"gross":gross,"expenses":operating,"net":net,"margin":net/sales*100 if sales else 0,"per_kg":net/sold if sold else 0}


PERMISSIONS={
 "ADMIN":{"*"},
 "MANAGER":{"dashboard","production","harvest","stock","sales","customers","suppliers","labour","raw_materials","purchases","expenses","payments","ledger","batch_cost","reports","charts"},
 "STAFF":{"dashboard","production.create","harvest.create","sales.create","customers.view","stock.view"},
}
_desktop_role="ADMIN"
def set_desktop_role(role):
    global _desktop_role;_desktop_role=(role or "STAFF").upper()
def enforce_desktop(action,role=None):return require_permission(role or _desktop_role,action)
def require_permission(role, action):
    allowed=PERMISSIONS.get((role or "").upper(),set())
    if "*" not in allowed and action not in allowed and action.split(".")[0] not in allowed:
        raise PermissionError(f"{role or 'Unknown'} is not allowed to perform {action}")
    return True

def post_ledger(conn, source_table, source_id, transaction_date, transaction_type, mode, amount, inflow=False, reference="", notes=""):
    amount=float(amount or 0)
    if amount < 0: raise ValueError("Ledger amount cannot be negative")
    conn.execute("DELETE FROM cash_ledger WHERE source_table=? AND source_id=?",(source_table,source_id))
    if amount and (mode or "").lower()!="credit":
        return conn.execute("INSERT INTO cash_ledger(transaction_date,transaction_type,reference,payment_mode,debit,credit,notes,source_table,source_id) VALUES(?,?,?,?,?,?,?,?,?)",(transaction_date,transaction_type,reference,mode,0 if inflow else amount,amount if inflow else 0,notes,source_table,source_id)).lastrowid
    return None

def delete_manual_ledger(ledger_id, conn=None):
    own=conn is None; conn=conn or get_connection()
    try:
        row=conn.execute("SELECT source_table FROM cash_ledger WHERE id=?",(ledger_id,)).fetchone()
        if not row:return False
        if row[0]:raise PermissionError("Source-linked ledger entries must be changed from their source transaction")
        conn.execute("DELETE FROM cash_ledger WHERE id=?",(ledger_id,))
        if own:conn.commit()
        return True
    finally:
        if own:conn.close()

def save_sale(data, sale_id=None, conn=None):
    enforce_desktop("sales.edit" if sale_id else "sales.create")
    own=conn is None; conn=conn or get_connection()
    try:
        qty=float(data["quantity_kg"]); available=mushroom_stock(conn, sale_id)
        total=validate_sale(qty,float(data["rate_per_kg"]),float(data.get("discount",0)),float(data.get("paid_amount",0)),available)
        batch_id=data.get("batch_id")
        batch_no=None
        if batch_id:
            row=conn.execute("SELECT batch_no FROM batches WHERE id=?",(batch_id,)).fetchone()
            if not row:raise ValueError("Invalid batch")
            batch_no=row[0]
        values=(data["invoice_no"],data["sale_date"],data.get("customer_id"),batch_id,batch_no,qty,float(data["rate_per_kg"]),float(data.get("discount",0)),total,float(data.get("paid_amount",0)),data.get("payment_mode","Cash"),data.get("notes",""))
        if sale_id:
            conn.execute("UPDATE sales SET invoice_no=?,sale_date=?,customer_id=?,batch_id=?,batch_no=?,quantity_kg=?,rate_per_kg=?,discount=?,total_amount=?,paid_amount=?,payment_mode=?,notes=? WHERE id=?",values+(sale_id,))
        else:
            sale_id=conn.execute("INSERT INTO sales(invoice_no,sale_date,customer_id,batch_id,batch_no,quantity_kg,rate_per_kg,discount,total_amount,paid_amount,payment_mode,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",values).lastrowid
        post_ledger(conn,"sales",sale_id,data["sale_date"],"SALE PAYMENT",data.get("payment_mode","Cash"),data.get("paid_amount",0),True,data["invoice_no"],data.get("notes",""))
        if own:conn.commit()
        publish("sale_changed");return sale_id
    finally:
        if own:conn.close()

def delete_sale(sale_id, conn=None):
    enforce_desktop("sales.delete")
    own=conn is None;conn=conn or get_connection()
    try:
        conn.execute("DELETE FROM cash_ledger WHERE source_table='sales' AND source_id=?",(sale_id,));conn.execute("DELETE FROM sales WHERE id=?",(sale_id,))
        if own:conn.commit()
        publish("sale_changed")
    finally:
        if own:conn.close()

def save_material_usage(data, usage_id=None):
    enforce_desktop("raw_materials.edit" if usage_id else "raw_materials.create")
    with get_connection() as conn:
        qty=float(data["quantity"])
        if qty<=0:raise ValueError("Quantity must be positive")
        available=raw_material_stock(data["material_id"],conn)
        if usage_id:
            old=conn.execute("SELECT material_id,quantity FROM material_usage WHERE id=?",(usage_id,)).fetchone()
            if not old:raise ValueError("Usage not found")
            if old[0]==data["material_id"]:available+=old[1]
        if qty>available:raise OverflowError("Insufficient raw material stock")
        batch=conn.execute("SELECT batch_no FROM batches WHERE id=?",(data.get("batch_id"),)).fetchone() if data.get("batch_id") else None
        vals=(data["usage_date"],data["material_id"],data.get("batch_id"),batch[0] if batch else None,qty,data.get("notes",""))
        if usage_id:conn.execute("UPDATE material_usage SET usage_date=?,material_id=?,batch_id=?,batch_no=?,quantity=?,notes=? WHERE id=?",vals+(usage_id,))
        else:usage_id=conn.execute("INSERT INTO material_usage(usage_date,material_id,batch_id,batch_no,quantity,notes) VALUES(?,?,?,?,?,?)",vals).lastrowid
        publish("material_changed");return usage_id

def save_material_adjustment(data, adjustment_id=None):
    enforce_desktop("raw_materials.edit" if adjustment_id else "raw_materials.create")
    with get_connection() as conn:
        qty=float(data["quantity"]);kind=data["adjustment_type"].upper();mid=data["material_id"]
        if qty<=0 or kind not in ("IN","OUT"):raise ValueError("Invalid adjustment")
        available=raw_material_stock(mid,conn)
        if adjustment_id:
            old=conn.execute("SELECT material_id,adjustment_type,quantity FROM material_adjustments WHERE id=?",(adjustment_id,)).fetchone()
            if old and old[0]==mid: available += old[2] if old[1]=='OUT' else -old[2]
        if kind=='OUT' and qty>available:raise OverflowError("Adjustment would make stock negative")
        vals=(data["adjustment_date"],mid,kind,qty,data.get("batch_id"),data.get("notes",""))
        if adjustment_id:conn.execute("UPDATE material_adjustments SET adjustment_date=?,material_id=?,adjustment_type=?,quantity=?,batch_id=?,notes=? WHERE id=?",vals+(adjustment_id,))
        else:adjustment_id=conn.execute("INSERT INTO material_adjustments(adjustment_date,material_id,adjustment_type,quantity,batch_id,notes) VALUES(?,?,?,?,?,?)",vals).lastrowid
        publish("material_changed");return adjustment_id

def delete_material_usage(usage_id):
    enforce_desktop("raw_materials.delete")
    with get_connection() as conn:result=conn.execute("DELETE FROM material_usage WHERE id=?",(usage_id,)).rowcount>0
    publish("material_changed");return result

def delete_material_adjustment(adjustment_id):
    enforce_desktop("raw_materials.delete")
    with get_connection() as conn:
        old=conn.execute("SELECT material_id,adjustment_type,quantity FROM material_adjustments WHERE id=?",(adjustment_id,)).fetchone()
        if not old:return False
        if old[1]=='IN' and raw_material_stock(old[0],conn)-old[2]<-1e-9:raise OverflowError("Deleting adjustment would make stock negative")
        conn.execute("DELETE FROM material_adjustments WHERE id=?",(adjustment_id,))
    publish("material_changed");return True

def save_expense(data, record_id=None):
    enforce_desktop("expenses.edit" if record_id else "expenses.create")
    with get_connection() as conn:
        amount=float(data["amount"])
        if amount<0:raise ValueError("Invalid expense")
        vals=(data["expense_date"],data["category"],data.get("description",""),amount,data.get("payment_mode","Cash"),data.get("batch_no",""),data.get("notes",""))
        if record_id:conn.execute("UPDATE expenses SET expense_date=?,category=?,description=?,amount=?,payment_mode=?,batch_no=?,notes=? WHERE id=?",vals+(record_id,))
        else:record_id=conn.execute("INSERT INTO expenses(expense_date,category,description,amount,payment_mode,batch_no,notes) VALUES(?,?,?,?,?,?,?)",vals).lastrowid
        post_ledger(conn,"expenses",record_id,data["expense_date"],"EXPENSE",data.get("payment_mode","Cash"),amount,False,"",data.get("notes",""));publish("expense_changed");return record_id

def save_purchase(data, record_id=None):
    enforce_desktop("purchases.edit" if record_id else "purchases.create")
    with get_connection() as conn:
        qty=float(data["quantity"]);rate=float(data["rate"]);paid=float(data.get("paid_amount",0));total=qty*rate
        if qty<=0 or rate<0 or paid<0 or paid>total:raise ValueError("Invalid purchase")
        material_id=data.get("material_id")
        material=conn.execute("SELECT item,unit FROM raw_materials WHERE id=?",(material_id,)).fetchone()
        if not material:raise ValueError("Invalid material")
        if " ".join(material[0].split()).casefold()=="other":
            custom_name=" ".join((data.get("material_name") or "").split())
            if not custom_name:raise ValueError("Material Name is required when Raw Material is Other")
            existing=None
            for candidate in conn.execute("SELECT id,item,unit FROM raw_materials"):
                if " ".join(candidate[1].split()).casefold()==custom_name.casefold():existing=candidate;break
            if existing:material_id,material_name,material_unit=existing
            else:
                material_unit=(data.get("unit") or "Kg").strip() or "Kg"
                material_id=conn.execute("INSERT INTO raw_materials(item,unit,opening_stock,reorder_level) VALUES(?,?,0,0)",(custom_name,material_unit)).lastrowid;material_name=custom_name
            material=(material_name,material_unit)
        vals=(data["purchase_date"],data.get("purchase_invoice",""),data.get("supplier_id"),material[0],material_id,qty,material[1],rate,total,paid,total-paid,data.get("batch_no",""),data.get("payment_mode","Cash"),data.get("notes",""))
        if record_id:conn.execute("UPDATE purchases SET purchase_date=?,purchase_invoice=?,supplier_id=?,item=?,material_id=?,quantity=?,unit=?,rate=?,total_amount=?,paid_amount=?,due_amount=?,batch_no=?,payment_mode=?,notes=? WHERE id=?",vals+(record_id,))
        else:record_id=conn.execute("INSERT INTO purchases(purchase_date,purchase_invoice,supplier_id,item,material_id,quantity,unit,rate,total_amount,paid_amount,due_amount,batch_no,payment_mode,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",vals).lastrowid
        post_ledger(conn,"purchases",record_id,data["purchase_date"],"PURCHASE PAYMENT",data.get("payment_mode","Cash"),paid,False,data.get("purchase_invoice",""),data.get("notes",""));publish("purchase_changed");return record_id

def save_labour(data, record_id=None):
    enforce_desktop("labour.edit" if record_id else "labour.create")
    with get_connection() as conn:
        days=float(data.get("days",0));hours=float(data.get("hours",0));rate=float(data.get("rate",0));amount=(days if days>0 else hours)*rate;paid=float(data.get("paid",0))
        if min(days,hours,rate,paid)<0 or paid>amount:raise ValueError("Invalid labour amount")
        vals=(data["worker_name"],data["work_date"],data.get("work_type",""),data.get("batch_no",""),days,hours,rate,amount,paid,data.get("payment_mode","Cash"),data.get("notes",""))
        if record_id:conn.execute("UPDATE labour SET worker_name=?,work_date=?,work_type=?,batch_no=?,days=?,hours=?,rate=?,amount=?,paid=?,payment_mode=?,notes=? WHERE id=?",vals+(record_id,))
        else:record_id=conn.execute("INSERT INTO labour(worker_name,work_date,work_type,batch_no,days,hours,rate,amount,paid,payment_mode,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)",vals).lastrowid
        post_ledger(conn,"labour",record_id,data["work_date"],"LABOUR IMMEDIATE PAYMENT",data.get("payment_mode","Cash"),paid,False,"",data.get("notes",""));publish("labour_changed");return record_id

def delete_source_record(table,record_id):
    enforce_desktop(f"{table}.delete")
    if table not in ("sales","expenses","purchases","labour"):raise ValueError("Unsupported source")
    with get_connection() as conn:
        conn.execute("DELETE FROM cash_ledger WHERE source_table=? AND source_id=?",(table,record_id));result=conn.execute(f"DELETE FROM {table} WHERE id=?",(record_id,)).rowcount>0
    publish(table+"_changed");return result

def save_batch(data,batch_id=None):
    enforce_desktop("production.edit" if batch_id else "production.create")
    vals=(data["batch_no"].strip(),data["production_date"],data.get("straw_type",""),float(data.get("straw_qty",0)),float(data.get("spawn_qty",0)),int(data.get("bag_count",0)),float(data.get("bag_size",0)),float(data.get("expected_yield",0)),data.get("expected_harvest_date") or None,data.get("room_rack",""),data.get("status","Preparing"),data.get("notes",""))
    if not vals[0] or min(vals[3],vals[4],vals[5],vals[6],vals[7])<0:raise ValueError("Invalid batch")
    with get_connection() as c:
        if batch_id:
            c.execute("UPDATE batches SET batch_no=?,production_date=?,straw_type=?,straw_qty=?,spawn_qty=?,bag_count=?,bag_size=?,expected_yield=?,expected_harvest_date=?,room_rack=?,status=?,notes=? WHERE id=?",vals+(batch_id,))
            c.execute("UPDATE daily_production SET batch_no=? WHERE batch_id=?",(vals[0],batch_id));c.execute("UPDATE harvests SET batch_no=? WHERE batch_id=?",(vals[0],batch_id));c.execute("UPDATE sales SET batch_no=? WHERE batch_id=?",(vals[0],batch_id))
        else:batch_id=c.execute("INSERT INTO batches(batch_no,production_date,straw_type,straw_qty,spawn_qty,bag_count,bag_size,expected_yield,expected_harvest_date,room_rack,status,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",vals).lastrowid
        publish("batch_changed");return batch_id

def delete_batch(batch_id):
    enforce_desktop("production.delete")
    with get_connection() as c:
        deps=sum(c.execute(f"SELECT COUNT(*) FROM {t} WHERE batch_id=?",(batch_id,)).fetchone()[0] for t in ("daily_production","harvests","sales","material_usage","material_adjustments"))
        if deps:raise ValueError("Batch has dependent records and cannot be deleted")
        result=c.execute("DELETE FROM batches WHERE id=?",(batch_id,)).rowcount>0
    publish("batch_changed");return result

def save_production(data,record_id=None):
    enforce_desktop("production.edit" if record_id else "production.create")
    gross=float(data["production_kg"]);waste=float(data.get("wastage_kg",0));bags=int(data.get("bags",0));bid=int(data["batch_id"])
    if min(gross,waste,bags)<0 or waste>gross:raise ValueError("Invalid production")
    with get_connection() as c:
        batch=c.execute("SELECT batch_no FROM batches WHERE id=?",(bid,)).fetchone()
        if not batch:raise ValueError("Invalid batch")
        vals=(data["production_date"],batch[0],bid,bags,gross,waste,gross-waste,data.get("room_rack",""),data.get("notes",""))
        if record_id:c.execute("UPDATE daily_production SET production_date=?,batch_no=?,batch_id=?,bags=?,production_kg=?,wastage_kg=?,saleable_kg=?,room_rack=?,notes=? WHERE id=?",vals+(record_id,))
        else:record_id=c.execute("INSERT INTO daily_production(production_date,batch_no,batch_id,bags,production_kg,wastage_kg,saleable_kg,room_rack,notes) VALUES(?,?,?,?,?,?,?,?,?)",vals).lastrowid
        publish("production_changed");return record_id

def delete_production(record_id):
    enforce_desktop("production.delete")
    with get_connection() as c:result=c.execute("DELETE FROM daily_production WHERE id=?",(record_id,)).rowcount>0
    publish("production_changed");return result

def save_harvest(data,record_id=None):
    enforce_desktop("harvest.edit" if record_id else "harvest.create")
    qty=float(data["quantity_kg"]);waste=float(data.get("wastage_kg",0));flush=int(data.get("flush_no",1));bid=int(data["batch_id"])
    if qty<0 or waste<0 or waste>qty or flush<1:raise ValueError("Invalid harvest")
    with get_connection() as c:
        batch=c.execute("SELECT batch_no FROM batches WHERE id=?",(bid,)).fetchone()
        if not batch:raise ValueError("Invalid batch")
        vals=(data["harvest_date"],batch[0],bid,flush,qty,waste,data.get("grade",""),data.get("notes",""))
        if record_id:c.execute("UPDATE harvests SET harvest_date=?,batch_no=?,batch_id=?,flush_no=?,quantity_kg=?,wastage_kg=?,grade=?,notes=? WHERE id=?",vals+(record_id,))
        else:record_id=c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,flush_no,quantity_kg,wastage_kg,grade,notes) VALUES(?,?,?,?,?,?,?,?)",vals).lastrowid
    publish("harvest_changed");return record_id

def delete_harvest(record_id):
    enforce_desktop("harvest.delete")
    with get_connection() as c:
        old=c.execute("SELECT quantity_kg-wastage_kg FROM harvests WHERE id=?",(record_id,)).fetchone()
        if not old:return False
        if mushroom_stock(c)-old[0]<-1e-9:raise OverflowError("Deleting harvest would make mushroom stock negative")
        c.execute("DELETE FROM harvests WHERE id=?",(record_id,))
    publish("harvest_changed");return True

def save_party(kind,data,record_id=None):
    table="customers" if kind=="customer" else "suppliers"
    enforce_desktop(f"{table}.edit" if record_id else f"{table}.create")
    name=data.get("name","").strip()
    if not name or float(data.get("opening_due",0))<0:raise ValueError("Invalid party")
    vals=(name,data.get("mobile",""),data.get("email",""),data.get("address",""),float(data.get("opening_due",0)),data.get("notes",""))
    with get_connection() as c:
        if record_id:c.execute(f"UPDATE {table} SET name=?,mobile=?,email=?,address=?,opening_due=?,notes=? WHERE id=?",vals+(record_id,))
        else:record_id=c.execute(f"INSERT INTO {table}(name,mobile,email,address,opening_due,notes) VALUES(?,?,?,?,?,?)",vals).lastrowid
    publish(table+"_changed");return record_id

def delete_party(kind,record_id):
    table="customers" if kind=="customer" else "suppliers";enforce_desktop(f"{table}.delete")
    dependencies=("sales","customer_payments") if kind=="customer" else ("purchases","supplier_payments")
    key="customer_id" if kind=="customer" else "supplier_id"
    with get_connection() as c:
        if any(c.execute(f"SELECT 1 FROM {t} WHERE {key}=? LIMIT 1",(record_id,)).fetchone() for t in dependencies):raise ValueError("Record has transaction history and cannot be deleted")
        return c.execute(f"DELETE FROM {table} WHERE id=?",(record_id,)).rowcount>0

def save_material(data,record_id=None):
    enforce_desktop("raw_materials.edit" if record_id else "raw_materials.create")
    item=data.get("item","").strip();opening=float(data.get("opening_stock",0));level=float(data.get("reorder_level",0))
    if not item or min(opening,level)<0:raise ValueError("Invalid material")
    vals=(item,data.get("unit","Kg"),opening,level)
    with get_connection() as c:
        if record_id:c.execute("UPDATE raw_materials SET item=?,unit=?,opening_stock=?,reorder_level=? WHERE id=?",vals+(record_id,))
        else:record_id=c.execute("INSERT INTO raw_materials(item,unit,opening_stock,reorder_level) VALUES(?,?,?,?)",vals).lastrowid
    publish("material_changed");return record_id

def delete_material(record_id):
    enforce_desktop("raw_materials.delete")
    with get_connection() as c:
        if any(c.execute(f"SELECT 1 FROM {t} WHERE material_id=? LIMIT 1",(record_id,)).fetchone() for t in ("purchases","material_usage","material_adjustments")):raise ValueError("Material has transaction history and cannot be deleted")
        return c.execute("DELETE FROM raw_materials WHERE id=?",(record_id,)).rowcount>0

def save_stock_adjustment(data,record_id=None):
    enforce_desktop("stock.edit" if record_id else "stock.create")
    qty=float(data["quantity_kg"]);kind=data.get("transaction_type","ADJUSTMENT IN").upper()
    if qty<=0 or kind not in ("ADJUSTMENT IN","ADJUSTMENT OUT","OPENING STOCK"):raise ValueError("Invalid stock adjustment")
    signed=qty if kind in ("ADJUSTMENT IN","OPENING STOCK") else -qty
    with get_connection() as c:
        available=mushroom_stock(c)
        if record_id:
            old=c.execute("SELECT quantity_kg FROM stock_transactions WHERE id=?",(record_id,)).fetchone()
            if not old:raise ValueError("Adjustment not found")
            available-=old[0]
        if available+signed< -1e-9:raise OverflowError("Adjustment would make stock negative")
        vals=(data["transaction_date"],kind,data.get("batch_no",""),signed,data.get("notes",""))
        if record_id:c.execute("UPDATE stock_transactions SET transaction_date=?,transaction_type=?,batch_no=?,quantity_kg=?,notes=? WHERE id=?",vals+(record_id,))
        else:record_id=c.execute("INSERT INTO stock_transactions(transaction_date,transaction_type,batch_no,quantity_kg,notes) VALUES(?,?,?,?,?)",vals).lastrowid
    publish("stock_changed");return record_id

def delete_stock_adjustment(record_id):
    enforce_desktop("stock.delete")
    with get_connection() as c:
        old=c.execute("SELECT quantity_kg FROM stock_transactions WHERE id=?",(record_id,)).fetchone()
        if not old:return False
        if mushroom_stock(c)-old[0]<-1e-9:raise OverflowError("Deleting adjustment would make stock negative")
        c.execute("DELETE FROM stock_transactions WHERE id=?",(record_id,))
    publish("stock_changed");return True

def batch_summary(batch_id,conn=None):
    own=conn is None;conn=conn or get_connection()
    try:
        row=conn.execute("SELECT batch_no,bag_count,straw_qty,spawn_qty,expected_yield FROM batches WHERE id=?",(batch_id,)).fetchone()
        if not row:return None
        actual=conn.execute("SELECT COALESCE(SUM(quantity_kg-wastage_kg),0) FROM harvests WHERE batch_id=?",(batch_id,)).fetchone()[0]
        labour=conn.execute("SELECT COALESCE(SUM(amount),0) FROM labour WHERE batch_id=? OR (batch_id IS NULL AND batch_no=?)",(batch_id,row[0])).fetchone()[0]
        other=conn.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE batch_id=? OR (batch_id IS NULL AND batch_no=?)",(batch_id,row[0])).fetchone()[0]
        return {"batch_no":row[0],"bags":row[1],"straw":row[2],"spawn":row[3],"expected_yield":row[4],"actual_harvest":actual,"yield_pct":actual/(row[4] or 1)*100 if row[4] else 0,"labour":labour,"other_cost":other}
    finally:
        if own:conn.close()

def customer_statement(customer_id,start=None,end=None):
    with get_connection() as c:
        opening=c.execute("SELECT opening_due FROM customers WHERE id=?",(customer_id,)).fetchone();balance=float(opening[0] or 0) if opening else 0;rows=[]
        events=[]
        for r in c.execute("SELECT sale_date,invoice_no,total_amount,paid_amount,id FROM sales WHERE customer_id=?",(customer_id,)):events.append((r[0],0,r[4],r[1],r[2],r[3]))
        for r in c.execute("SELECT payment_date,COALESCE(reference_no,''),amount,id FROM customer_payments WHERE customer_id=?",(customer_id,)):events.append((r[0],1,r[3],r[1],0,r[2]))
        for dt,kind,rid,ref,debit,credit in sorted(events):
            if start and dt<start:balance+=debit-credit;continue
            if end and dt>end:continue
            balance+=debit-credit;rows.append((dt,ref,debit,credit,balance))
        return balance-float(sum(r[2]-r[3] for r in rows)),rows

def supplier_statement(supplier_id,start=None,end=None):
    with get_connection() as c:
        opening=c.execute("SELECT opening_due FROM suppliers WHERE id=?",(supplier_id,)).fetchone();balance=float(opening[0] or 0) if opening else 0;rows=[];events=[]
        for r in c.execute("SELECT purchase_date,COALESCE(purchase_invoice,''),total_amount,paid_amount,id FROM purchases WHERE supplier_id=?",(supplier_id,)):events.append((r[0],0,r[4],r[1],r[2],r[3]))
        for r in c.execute("SELECT payment_date,COALESCE(reference_no,''),amount,id FROM supplier_payments WHERE supplier_id=?",(supplier_id,)):events.append((r[0],1,r[3],r[1],0,r[2]))
        for dt,kind,rid,ref,debit,credit in sorted(events):
            if start and dt<start:balance+=debit-credit;continue
            if end and dt>end:continue
            balance+=debit-credit;rows.append((dt,ref,debit,credit,balance))
        return balance-float(sum(r[2]-r[3] for r in rows)),rows

def low_stock_materials():
    with get_connection() as c:
        return [(i,n,u,raw_material_stock(i,c),level) for i,n,u,level in c.execute("SELECT id,item,unit,reorder_level FROM raw_materials") if raw_material_stock(i,c)<=float(level or 0)]

def invoice_data(sale_id):
    with get_connection() as c:
        r=c.execute("""SELECT s.invoice_no,s.sale_date,COALESCE(c.name,'Cash Customer'),COALESCE(c.mobile,''),COALESCE(c.address,''),COALESCE(b.batch_no,'Unallocated'),s.quantity_kg,s.rate_per_kg,s.discount,s.quantity_kg*s.rate_per_kg,s.total_amount,s.paid_amount,s.total_amount-s.paid_amount,s.payment_mode,s.notes FROM sales s LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN batches b ON b.id=s.batch_id WHERE s.id=?""",(sale_id,)).fetchone()
    if not r:raise ValueError("Sale not found")
    keys=("invoice_no","date","customer","customer_mobile","customer_address","batch","quantity","rate","discount","gross","net","paid","due","payment_mode","notes")
    data=dict(zip(keys,r));data.update({k:setting(k) for k in ("business_name","address","mobile","gstin","logo")});return data
