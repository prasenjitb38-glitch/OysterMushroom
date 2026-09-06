import io, os, secrets, sqlite3, time, tempfile
from functools import wraps
from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify,send_file

from database import authenticate, create_database, get_connection
from invoice_pdf import generate_invoice_pdf_file
from payment_service import record_payment
from services import (
    customer_outstanding,
    generate_invoice_no,
    mushroom_stock,
    pnl,
    supplier_outstanding,
    validate_sale,
    require_permission, save_sale,
)

create_database()
app = Flask(__name__)
production_mode=os.environ.get("APP_ENV",os.environ.get("FLASK_ENV","development")).lower()=="production"
configured_secret=os.environ.get("SECRET_KEY")
if production_mode and (not configured_secret or len(configured_secret)<32):raise RuntimeError("A strong SECRET_KEY (32+ characters) is required in production")
app.secret_key=configured_secret or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_SECURE=production_mode)
from web_crud import crud
app.register_blueprint(crud)
_attempts={}

@app.before_request
def csrf_protect():
    if request.method=="POST":
        supplied=request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not supplied or not secrets.compare_digest(str(supplied),str(session.get("csrf_token",""))):return "Invalid CSRF token",400
    user=session.get("user")
    if user and user.get("must_change_password") and request.endpoint not in ("change_password_route","logout","static"):
        return redirect(url_for("change_password_route"))

@app.context_processor
def csrf_context():
    if "csrf_token" not in session:session["csrf_token"]=secrets.token_urlsafe(32)
    nav=[]
    for label,endpoint,action in NAV_ITEMS:
        try:
            if session.get("user"):require_permission(session["user"].get("role"),action)
            else:continue
        except PermissionError:continue
        nav.append((label,endpoint))
    return {"csrf_token":session["csrf_token"],"navigation":nav}

NAV_ITEMS=(
 ("🏠 Dashboard","dashboard","dashboard"),("🌱 Production","production","production.create"),("🍄 Harvest","harvest","harvest.create"),("📦 Stock","stock","stock.view"),("🛒 Sales","sales","sales.create"),("🧪 Raw Materials","raw_materials_web","raw_materials"),("🧺 Purchases","purchases_web","purchases"),("💰 Expenses","expenses_web","expenses"),("👥 Customers","customers_web","customers.view"),("🚚 Suppliers","suppliers_web","suppliers"),("👷 Labour","labour_web","labour"),("💳 Payments","payments_web","payments"),("🏦 Cash / Bank","ledger_web","ledger"),("🧮 Batch Cost","batch_cost_web","batch_cost"),("📈 Profit & Loss","pnl_web","reports"),("📊 Reports","reports_web","reports"),("📉 Charts","charts_web","charts"),("🧾 Invoices","invoices_web","sales.create"),("⚙ Settings","settings_web","settings"),("🔐 Users","users_web","users"),("💾 Backup / Restore","backup_web","backup_restore"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"): return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def permission(action):
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*args,**kwargs):
            try:require_permission(session["user"]["role"],action)
            except PermissionError:return "Forbidden",403
            return view(*args,**kwargs)
        return wrapped
    return deco

def number(name,minimum=0):
    value=float(request.form.get(name,""))
    if value<minimum:raise ValueError(f"Invalid {name}")
    return value


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username=request.form.get("username","").strip().lower();key=(request.remote_addr or "local",username);now=time.time();attempt=[t for t in _attempts.get(key,[]) if now-t<300]
        if len(attempt)>=5:return "Too many login attempts. Try again later.",429
        row = authenticate(username, request.form.get("password",""))
        if row:
            _attempts.pop(key,None);session["user"]={"id":row[0],"name":row[4] or username,"role":row[2],"must_change_password":bool(row[5])}
            if row[5]:return redirect(url_for("change_password_route"))
            return redirect(url_for("dashboard"))
        attempt.append(now);_attempts[key]=attempt
        flash("Username বা password সঠিক নয়।", "error")
    return render_template("login.html")


@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/change-password",methods=["GET","POST"])
@login_required
def change_password_route():
    if request.method=="POST":
        from database import change_password
        try:change_password(session["user"]["id"],request.form.get("current_password",""),request.form.get("new_password",""));session["user"]["must_change_password"]=False;session.modified=True;return redirect(url_for("dashboard"))
        except ValueError as e:flash(str(e),"error")
    return render_template("change_password.html")


@app.route("/")
@login_required
def dashboard():
    with get_connection() as c:
        stats={
            "batches":c.execute("SELECT COUNT(*) FROM batches WHERE LOWER(status) NOT IN ('completed','failed')").fetchone()[0],
            "production":c.execute("SELECT COALESCE(SUM(production_kg),0) FROM daily_production").fetchone()[0],
            "harvest":c.execute("SELECT COALESCE(SUM(quantity_kg-wastage_kg),0) FROM harvests").fetchone()[0],
            "sales":c.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales").fetchone()[0],
            "expenses":c.execute("SELECT COALESCE(SUM(amount),0) FROM expenses").fetchone()[0],
        }
        recent=c.execute("SELECT production_date,batch_no,production_kg,wastage_kg,saleable_kg FROM daily_production ORDER BY id DESC LIMIT 10").fetchall()
    stats.update(stock=mushroom_stock(),customer_due=customer_outstanding(),supplier_due=supplier_outstanding(),net=pnl()["net"])
    return render_template("dashboard.html",stats=stats,recent=recent)


@app.route("/production", methods=["GET", "POST"])
@permission("production.create")
def production():
    with get_connection() as c:
        if request.method == "POST":
            try:
                batch=request.form.get("batch_no","").strip();gross=number("production");waste=number("wastage");bags=int(number("bags"));found=c.execute("SELECT id FROM batches WHERE batch_no=?",(batch,)).fetchone()
                if waste>gross or not found:raise ValueError("Production/Wastage/Batch is invalid")
                c.execute("INSERT INTO daily_production(production_date,batch_no,batch_id,bags,production_kg,wastage_kg,saleable_kg) VALUES(?,?,?,?,?,?,?)",(request.form.get("date",""),batch,found[0],bags,gross,waste,gross-waste));flash("Production saved.","success")
            except (ValueError,TypeError):flash("Invalid production form values.","error")
        rows=c.execute("SELECT id,production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg FROM daily_production ORDER BY id DESC").fetchall();batches=c.execute("SELECT batch_no FROM batches ORDER BY id DESC").fetchall();batch_rows=c.execute("SELECT id,batch_no,production_date,bag_count,expected_yield,status FROM batches ORDER BY id DESC").fetchall()
    return render_template("entry.html",title="Production & Batches",kind="production",rows=rows,batches=batches,batch_rows=batch_rows)


@app.route("/harvest", methods=["GET", "POST"])
@permission("harvest.create")
def harvest():
    with get_connection() as c:
        if request.method == "POST":
            try:
                q=number("quantity");w=number("wastage");batch=request.form.get("batch_no","");found=c.execute("SELECT id FROM batches WHERE batch_no=?",(batch,)).fetchone();flush=int(number("flush",1))
                if w>q or not found:raise ValueError
                c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,flush_no,quantity_kg,wastage_kg,grade,notes) VALUES(?,?,?,?,?,?,?,?)",(request.form.get("date",""),batch,found[0],flush,q,w,request.form.get("grade",""),request.form.get("notes","")));flash("Harvest saved.","success")
            except (ValueError,TypeError):flash("Invalid harvest form values.","error")
        rows=c.execute("SELECT id,harvest_date,batch_no,flush_no,quantity_kg,wastage_kg,quantity_kg-wastage_kg FROM harvests ORDER BY id DESC").fetchall();batches=c.execute("SELECT batch_no FROM batches ORDER BY id DESC").fetchall()
    return render_template("entry.html",title="Harvest",kind="harvest",rows=rows,batches=batches)


@app.route("/sales", methods=["GET", "POST"])
@permission("sales.create")
def sales():
    with get_connection() as c:
        if request.method == "POST":
            try:
                qty=number("quantity",.000001);rate=number("rate",.000001);discount=number("discount");paid=number("paid");batch_id=int(request.form["batch_id"]) if request.form.get("batch_id") else None
                save_sale({"invoice_no":generate_invoice_no(),"sale_date":request.form["date"],"batch_id":batch_id,"quantity_kg":qty,"rate_per_kg":rate,"discount":discount,"paid_amount":paid,"payment_mode":request.form.get("mode","Cash"),"notes":request.form.get("notes","")},conn=c);flash("Sale saved.","success")
            except (ValueError,OverflowError,TypeError) as e:flash(str(e),"error")
        rows=c.execute("SELECT id,invoice_no,sale_date,quantity_kg,rate_per_kg,total_amount,paid_amount,total_amount-paid_amount FROM sales ORDER BY id DESC").fetchall()
        batches=c.execute("SELECT id,batch_no FROM batches ORDER BY batch_no").fetchall()
    return render_template("entry.html",title="Sales",kind="sales",rows=rows,stock=mushroom_stock(),batches=batches)


@app.route("/stock")
@permission("stock.view")
def stock():
    with get_connection() as c:rows=c.execute("SELECT id,transaction_date,transaction_type,batch_no,quantity_kg,notes FROM stock_transactions ORDER BY id DESC").fetchall()
    return render_template("stock_web.html",stock=mushroom_stock(),rows=rows)

def table_page(title,headers,sql,params=(),**extra):
    with get_connection() as c:rows=c.execute(sql,params).fetchall()
    return render_template("module_web.html",title=title,headers=headers,rows=rows,**extra)

@app.route("/raw-materials")
@permission("raw_materials")
def raw_materials_web():
    from services import raw_material_stock
    with get_connection() as c:rows=[(r[0],r[1],r[2],r[3],raw_material_stock(r[0],c),"LOW" if raw_material_stock(r[0],c)<=r[3] else "OK") for r in c.execute("SELECT id,item,unit,reorder_level FROM raw_materials ORDER BY item")]
    with get_connection() as c:usage=c.execute("SELECT u.id,u.usage_date,m.item,COALESCE(b.batch_no,''),u.quantity FROM material_usage u JOIN raw_materials m ON m.id=u.material_id LEFT JOIN batches b ON b.id=u.batch_id ORDER BY u.id DESC").fetchall();adjustments=c.execute("SELECT a.id,a.adjustment_date,m.item,a.adjustment_type,a.quantity FROM material_adjustments a JOIN raw_materials m ON m.id=a.material_id ORDER BY a.id DESC").fetchall()
    return render_template("module_web.html",title="Raw Materials",headers=("ID","Material","Unit","Minimum","Current Stock","Status"),rows=rows,create_resource="material",action_resource="material",secondary=(("Material Usage",("ID","Date","Material","Batch","Quantity"),usage,"usage"),("Material Adjustments",("ID","Date","Material","Type","Quantity"),adjustments,"adjustment")),extra_creates=(("+ Material Usage","usage"),("+ Stock Adjustment","adjustment")))

@app.route("/purchases")
@permission("purchases")
def purchases_web():return table_page("Purchases",("ID","Date","Invoice","Supplier","Material","Quantity","Total","Paid","Due"),"SELECT p.id,p.purchase_date,COALESCE(p.purchase_invoice,''),COALESCE(s.name,''),p.item,p.quantity,p.total_amount,p.paid_amount,p.due_amount FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id ORDER BY p.id DESC",create_resource="purchase",action_resource="purchase")

@app.route("/expenses")
@permission("expenses")
def expenses_web():return table_page("Expenses",("ID","Date","Category","Description","Amount","Mode","Batch"),"SELECT id,expense_date,category,description,amount,payment_mode,batch_no FROM expenses ORDER BY id DESC",create_resource="expense",action_resource="expense")

@app.route("/customers")
@permission("customers.view")
def customers_web():
    q="%"+request.args.get("q","").strip()+"%"
    return table_page("Customers",("ID","Name","Mobile","Address","Opening Due"),"SELECT id,name,mobile,address,opening_due FROM customers WHERE name LIKE ? OR mobile LIKE ? ORDER BY name",(q,q),create_resource="customer",action_resource="customer",statement_resource="customer",search=True)

@app.route("/suppliers")
@permission("suppliers")
def suppliers_web():
    q="%"+request.args.get("q","").strip()+"%"
    return table_page("Suppliers",("ID","Name","Mobile","Address","Opening Due"),"SELECT id,name,mobile,address,opening_due FROM suppliers WHERE name LIKE ? OR mobile LIKE ? ORDER BY name",(q,q),create_resource="supplier",action_resource="supplier",statement_resource="supplier",search=True)

@app.route("/labour")
@permission("labour")
def labour_web():return table_page("Labour",("ID","Worker","Date","Work","Batch","Amount","Paid","Due"),"""SELECT id,worker_name,work_date,work_type,batch_no,amount,paid,
    amount-paid-COALESCE((SELECT SUM(p.amount) FROM labour_payments p WHERE p.labour_id=labour.id),0)
    FROM labour ORDER BY id DESC""",create_resource="labour",action_resource="labour")

@app.route("/payments",methods=["GET","POST"])
@permission("payments")
def payments_web():
    if request.method=="POST":
        try:record_payment(request.form["date"],request.form["payment_type"],int(request.form["party_id"]),number("amount",.000001),request.form.get("mode","Cash"),request.form.get("reference",""));flash("Payment saved.","success")
        except (ValueError,PermissionError,KeyError) as e:flash(str(e),"error")
        except sqlite3.Error:
            app.logger.exception("Payment transaction failed")
            flash("Payment could not be saved; no account balances were changed.","error")
        return redirect(url_for("payments_web"))
    with get_connection() as c:parties={"CUSTOMER PAYMENT":c.execute("SELECT id,name FROM customers ORDER BY name").fetchall(),"SUPPLIER PAYMENT":c.execute("SELECT id,name FROM suppliers ORDER BY name").fetchall(),"LABOUR PAYMENT":c.execute("SELECT id,worker_name FROM labour ORDER BY worker_name").fetchall()}
    return table_page("Payments",("ID","Date","Type","Reference","Mode","Outflow","Inflow"),"SELECT id,transaction_date,transaction_type,reference,payment_mode,debit,credit FROM cash_ledger WHERE source_table IN ('customer_payments','supplier_payments','labour_payments') ORDER BY id DESC",payment_parties=parties,action_resource="payment")

@app.route("/cash-bank")
@permission("ledger")
def ledger_web():
    start=request.args.get("start","").strip();end=request.args.get("end","").strip();mode=request.args.get("mode","All").strip();kind=request.args.get("type","").strip()
    clauses=[];params=[]
    if start:clauses.append("transaction_date>=?");params.append(start)
    if end:clauses.append("transaction_date<=?");params.append(end)
    if kind:clauses.append("transaction_type=?");params.append(kind)
    summary_where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    summary_params=list(params)
    if mode=="Cash":clauses.append("LOWER(payment_mode)='cash'")
    elif mode=="Bank":clauses.append("LOWER(payment_mode) IN ('bank','upi','online')")
    where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
    with get_connection() as c:
        rows=c.execute("SELECT transaction_date,transaction_type,reference,payment_mode,debit,credit FROM cash_ledger"+where+" ORDER BY transaction_date DESC,id DESC",params).fetchall()
        summary_rows=c.execute("SELECT transaction_date,transaction_type,reference,payment_mode,debit,credit FROM cash_ledger"+summary_where,summary_params).fetchall()
        types=[r[0] for r in c.execute("SELECT DISTINCT transaction_type FROM cash_ledger WHERE COALESCE(transaction_type,'')<>'' ORDER BY transaction_type")]
        opening_cash=float(c.execute("SELECT COALESCE((SELECT value FROM settings WHERE key='opening_cash'),'0')").fetchone()[0] or 0)
        opening_bank=float(c.execute("SELECT COALESCE((SELECT value FROM settings WHERE key='opening_bank'),'0')").fetchone()[0] or 0)
        prior_cash=prior_bank=0.0
        if start:
            prior_cash=c.execute("SELECT COALESCE(SUM(credit-debit),0) FROM cash_ledger WHERE transaction_date<? AND LOWER(payment_mode)='cash'",(start,)).fetchone()[0]
            prior_bank=c.execute("SELECT COALESCE(SUM(credit-debit),0) FROM cash_ledger WHERE transaction_date<? AND LOWER(payment_mode) IN ('bank','upi','online')",(start,)).fetchone()[0]
    def totals(which,opening):
        selected=[r for r in summary_rows if which=="All" or (which=="Cash" and str(r[3]).lower()=="cash") or (which=="Bank" and str(r[3]).lower() in ("bank","upi","online"))]
        outflow=sum(float(r[4] or 0) for r in selected);inflow=sum(float(r[5] or 0) for r in selected)
        return {"opening":opening,"inflow":inflow,"outflow":outflow,"closing":opening+inflow-outflow}
    cash=totals("Cash",opening_cash+prior_cash);bank=totals("Bank",opening_bank+prior_bank)
    summary={"Cash":cash,"Bank":bank,"Overall":{k:cash[k]+bank[k] for k in cash}}
    return render_template("module_web.html",title="Cash / Bank Ledger",headers=("Date","Type","Reference","Mode","Outflow","Inflow"),rows=rows,ledger_summary=summary,ledger_types=types)

@app.route("/batch-cost")
@permission("batch_cost")
def batch_cost_web():
    from services import batch_cost_rows
    return render_template("module_web.html",title="Batch Cost",headers=("Batch","Date","Bags","Production","Wastage","Saleable","Total Cost","Cost/Bag","Cost/Kg","Expected Sales","Expected Profit"),rows=batch_cost_rows())

@app.route("/profit-loss")
@permission("reports")
def pnl_web():
    result=pnl(request.args.get("start"),request.args.get("end"));return render_template("module_web.html",title="Profit & Loss",headers=("Sales","COGS","Gross","Expenses","Net","Margin %","Profit/Kg"),rows=[tuple(result[k] for k in ("sales","cogs","gross","expenses","net","margin","per_kg"))],date_filter=True)

@app.route("/reports")
@permission("reports")
def reports_web():
    from services import cash_balance,labour_due
    return render_template("module_web.html",title="Business Reports",headers=("Metric","Value"),rows=(("Mushroom Stock",mushroom_stock()),("Customer Due",customer_outstanding()),("Supplier Due",supplier_outstanding()),("Labour Due",labour_due()),("Cash",cash_balance("Cash")),("Bank",cash_balance("Bank"))),date_filter=True)

@app.route("/charts")
@permission("charts")
def charts_web():return render_template("module_web.html",title="Charts",headers=(),rows=(),chart_url=url_for("chart_download"))

@app.route("/invoices")
@permission("sales.create")
def invoices_web():return table_page("Invoices",("ID","Invoice","Date","Customer","Total","Paid","Due","PDF"),"SELECT s.id,s.invoice_no,s.sale_date,COALESCE(c.name,'Cash Customer'),s.total_amount,s.paid_amount,s.total_amount-s.paid_amount,'PDF' FROM sales s LEFT JOIN customers c ON c.id=s.customer_id ORDER BY s.id DESC",invoice_links=True)

@app.route("/settings",methods=["GET","POST"])
@permission("settings")
def settings_web():
    if request.method=="POST":
        allowed=("business_name","address","mobile","email","gstin","invoice_prefix","opening_cash","opening_bank","opening_mushroom_stock","default_payment_mode","units","expected_rate")
        try:
            if any(float(request.form.get(k,0) or 0)<0 for k in ("opening_cash","opening_bank","opening_mushroom_stock","expected_rate")):raise ValueError
        except ValueError:
            flash("Opening balances and expected rate must be non-negative numbers.","error");return redirect(url_for("settings_web"))
        with get_connection() as c:c.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[(k,request.form.get(k,"").strip()) for k in allowed])
        flash("Settings saved.","success");return redirect(url_for("settings_web"))
    with get_connection() as c:values=dict(c.execute("SELECT key,value FROM settings"))
    return render_template("module_web.html",title="Settings",headers=(),rows=(),settings_values=values)

@app.route("/users")
@permission("users")
def users_web():return table_page("Users",("ID","Username","Name","Role","Active","Must Change Password"),"SELECT id,username,full_name,role,active,must_change_password FROM users ORDER BY username",create_resource="user",user_actions=True)

@app.route("/backup")
@permission("backup_restore")
def backup_web():return render_template("module_web.html",title="Backup / Restore",headers=(),rows=(),backup_tools=True)

@app.route("/api/payments/<kind>",methods=["POST"])
@permission("payments.create")
def payment_api(kind):
    kinds={"customer":"CUSTOMER PAYMENT","supplier":"SUPPLIER PAYMENT","labour":"LABOUR PAYMENT"}
    if kind not in kinds:return jsonify(error="Unknown payment type"),404
    try:return jsonify(ok=True,ledger_id=record_payment(request.form.get("date",""),kinds[kind],int(request.form.get("party_id","")),number("amount",.000001),request.form.get("mode","Cash"),request.form.get("reference",""),request.form.get("notes",""))),201
    except (ValueError,PermissionError) as e:return jsonify(error=str(e)),400
    except sqlite3.Error:
        app.logger.exception("Payment API transaction failed")
        return jsonify(error="Payment could not be saved; no account balances were changed."),503

@app.route("/api/reports")
@permission("reports")
def reports_api():
    from services import cash_balance,labour_due,raw_material_stock,batch_cost_rows
    with get_connection() as c:materials=[{"id":r[0],"item":r[1],"stock":raw_material_stock(r[0],c)} for r in c.execute("SELECT id,item FROM raw_materials")]
    return jsonify(pnl=pnl(request.args.get("start"),request.args.get("end")),mushroom_stock=mushroom_stock(),customer_due=customer_outstanding(),supplier_due=supplier_outstanding(),labour_due=labour_due(),cash=cash_balance("Cash"),bank=cash_balance("Bank"),materials=materials,batches=batch_cost_rows())

@app.route("/charts.png")
@permission("charts")
def chart_download():
    from modules.analytics import generate_chart_file
    path=os.path.join(tempfile.gettempdir(),f"mushroom-chart-{secrets.token_hex(6)}.png");generate_chart_file(path);return send_file(path,mimetype="image/png",download_name="business-charts.png")

@app.route("/invoice/<int:sale_id>.pdf")
@permission("sales.create")
def invoice_download(sale_id):
    try:
        output=io.BytesIO();generate_invoice_pdf_file(sale_id,output);output.seek(0)
    except ValueError:return jsonify(error="Invoice not found"),404
    except Exception:
        app.logger.exception("Invoice PDF generation failed for sale %s",sale_id)
        return jsonify(error="Invoice PDF is temporarily unavailable"),503
    return send_file(output,mimetype="application/pdf",download_name=f"invoice-{sale_id}.pdf",as_attachment=request.args.get("download")=="1")

@app.route("/backup/download")
@permission("backup_restore")
def backup_download():
    import database
    return send_file(database.DB_FILE,mimetype="application/vnd.sqlite3",download_name="mushroom-backup.db",as_attachment=True)

@app.route("/backup/restore",methods=["POST"])
@permission("backup_restore")
def backup_restore_api():
    import database
    from modules.system_tools import restore_database
    upload=request.files.get("backup")
    if not upload:return jsonify(error="Backup file required"),400
    path=os.path.join(tempfile.gettempdir(),f"restore-{secrets.token_hex(8)}.db");upload.save(path)
    try:restore_database(path,database.DB_FILE)
    except (ValueError,OSError) as e:return jsonify(error=str(e)),400
    finally:
        try:os.remove(path)
        except OSError:pass
    return jsonify(ok=True)

@app.route("/health")
def health():
    import database
    db_dir=os.path.abspath(database.DB_FOLDER)
    db_file=os.path.abspath(database.DB_FILE)
    normalized=db_file.replace("\\","/")
    data_root="/var/data"
    try:
        disk_mounted=os.path.ismount(data_root)
        if os.path.exists("/proc/mounts"):
            with open("/proc/mounts",encoding="utf-8") as mounts:
                disk_mounted=disk_mounted or any(line.split()[1]==data_root for line in mounts if len(line.split())>1)
    except OSError:disk_mounted=False
    try:
        with get_connection() as c: integrity=c.execute("PRAGMA integrity_check").fetchone()[0]
    except Exception:
        return jsonify(status="error"),503
    persistent_path=normalized.startswith(data_root+"/")
    return jsonify(status="ok" if integrity=="ok" else "error",integrity=integrity,commit=os.environ.get("RENDER_GIT_COMMIT","local"),app_env=os.environ.get("APP_ENV","development"),database_directory=db_dir,database_file=db_file,directory_exists=os.path.isdir(db_dir),database_exists=os.path.isfile(db_file),path_under_var_data=persistent_path,persistent_disk_mounted=disk_mounted,persistent_database=persistent_path and disk_mounted),200 if integrity=="ok" else 503


if __name__ == "__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
