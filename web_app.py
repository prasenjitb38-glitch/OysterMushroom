import os
from functools import wraps
from flask import Flask, flash, redirect, render_template, request, session, url_for

from database import create_database, get_connection
from modules.system_tools import authenticate
from modules.sales import SalesPage
from services import customer_outstanding, mushroom_stock, pnl, supplier_outstanding

create_database()
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-production")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"): return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        row = authenticate(request.form["username"], request.form["password"])
        if row:
            session["user"] = {"name": row[4] or request.form["username"], "role": row[2]}
            return redirect(url_for("dashboard"))
        flash("Username বা password সঠিক নয়।", "error")
    return render_template("login.html")


@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))


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
@login_required
def production():
    with get_connection() as c:
        if request.method == "POST":
            batch=request.form["batch_no"].strip(); gross=float(request.form["production"]); waste=float(request.form["wastage"])
            if gross < 0 or waste < 0 or waste > gross: flash("Production/Wastage সঠিক নয়।","error")
            elif not c.execute("SELECT 1 FROM batches WHERE batch_no=?",(batch,)).fetchone(): flash("Batch পাওয়া যায়নি।","error")
            else:
                c.execute("INSERT INTO daily_production(production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg) VALUES(?,?,?,?,?,?)",(request.form["date"],batch,int(request.form["bags"] or 0),gross,waste,gross-waste));flash("Production saved.","success")
        rows=c.execute("SELECT production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg FROM daily_production ORDER BY id DESC").fetchall();batches=c.execute("SELECT batch_no FROM batches ORDER BY id DESC").fetchall()
    return render_template("entry.html",title="Daily Production",kind="production",rows=rows,batches=batches)


@app.route("/harvest", methods=["GET", "POST"])
@login_required
def harvest():
    with get_connection() as c:
        if request.method == "POST":
            q=float(request.form["quantity"]);w=float(request.form["wastage"]);batch=request.form["batch_no"]
            if q<0 or w<0 or w>q:flash("Harvest/Wastage সঠিক নয়।","error")
            else:c.execute("INSERT INTO harvests(harvest_date,batch_no,flush_no,quantity_kg,wastage_kg,grade,notes) VALUES(?,?,?,?,?,?,?)",(request.form["date"],batch,int(request.form["flush"]),q,w,request.form["grade"],request.form.get("notes","")));flash("Harvest saved.","success")
        rows=c.execute("SELECT harvest_date,batch_no,flush_no,quantity_kg,wastage_kg,quantity_kg-wastage_kg FROM harvests ORDER BY id DESC").fetchall();batches=c.execute("SELECT batch_no FROM batches ORDER BY id DESC").fetchall()
    return render_template("entry.html",title="Harvest",kind="harvest",rows=rows,batches=batches)


@app.route("/sales", methods=["GET", "POST"])
@login_required
def sales():
    with get_connection() as c:
        if request.method == "POST":
            qty=float(request.form["quantity"]);rate=float(request.form["rate"]);discount=float(request.form.get("discount",0));paid=float(request.form.get("paid",0));total=qty*rate-discount
            try: SalesPage.validate_sale(qty,rate,discount,paid,mushroom_stock())
            except (ValueError,OverflowError) as e:flash(str(e),"error")
            else:c.execute("INSERT INTO sales(invoice_no,sale_date,quantity_kg,rate_per_kg,discount,total_amount,paid_amount,payment_mode,notes) VALUES(?,?,?,?,?,?,?,?,?)",(SalesPage.generate_invoice_no(),request.form["date"],qty,rate,discount,total,paid,request.form["mode"],request.form.get("notes","")));flash("Sale saved.","success")
        rows=c.execute("SELECT invoice_no,sale_date,quantity_kg,rate_per_kg,total_amount,paid_amount,total_amount-paid_amount FROM sales ORDER BY id DESC").fetchall()
    return render_template("entry.html",title="Sales",kind="sales",rows=rows,stock=mushroom_stock())


@app.route("/stock")
@login_required
def stock(): return render_template("stock_web.html",stock=mushroom_stock())


if __name__ == "__main__": app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
