import os, secrets, time, tempfile
from functools import wraps
from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify,send_file

from database import authenticate, create_database, get_connection
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
    return {"csrf_token":session["csrf_token"]}


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
        rows=c.execute("SELECT production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg FROM daily_production ORDER BY id DESC").fetchall();batches=c.execute("SELECT batch_no FROM batches ORDER BY id DESC").fetchall()
    return render_template("entry.html",title="Daily Production",kind="production",rows=rows,batches=batches)


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
        rows=c.execute("SELECT harvest_date,batch_no,flush_no,quantity_kg,wastage_kg,quantity_kg-wastage_kg FROM harvests ORDER BY id DESC").fetchall();batches=c.execute("SELECT batch_no FROM batches ORDER BY id DESC").fetchall()
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
        rows=c.execute("SELECT invoice_no,sale_date,quantity_kg,rate_per_kg,total_amount,paid_amount,total_amount-paid_amount FROM sales ORDER BY id DESC").fetchall()
        batches=c.execute("SELECT id,batch_no FROM batches ORDER BY batch_no").fetchall()
    return render_template("entry.html",title="Sales",kind="sales",rows=rows,stock=mushroom_stock(),batches=batches)


@app.route("/stock")
@login_required
def stock(): return render_template("stock_web.html",stock=mushroom_stock())

@app.route("/api/payments/<kind>",methods=["POST"])
@permission("payments.create")
def payment_api(kind):
    from modules.accounts import record_payment
    kinds={"customer":"CUSTOMER PAYMENT","supplier":"SUPPLIER PAYMENT","labour":"LABOUR PAYMENT"}
    if kind not in kinds:return jsonify(error="Unknown payment type"),404
    try:return jsonify(ok=True,ledger_id=record_payment(request.form.get("date",""),kinds[kind],int(request.form.get("party_id","")),number("amount",.000001),request.form.get("mode","Cash"),request.form.get("reference",""),request.form.get("notes",""))),201
    except (ValueError,PermissionError) as e:return jsonify(error=str(e)),400

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
    from modules.sales import generate_invoice_pdf_file
    try:path=os.path.join(tempfile.gettempdir(),f"invoice-{sale_id}-{secrets.token_hex(5)}.pdf");generate_invoice_pdf_file(sale_id,path)
    except ValueError:return jsonify(error="Invoice not found"),404
    return send_file(path,mimetype="application/pdf",download_name=f"invoice-{sale_id}.pdf",as_attachment=request.args.get("download")=="1")

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


if __name__ == "__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
