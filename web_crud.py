import sqlite3
from flask import Blueprint,flash,redirect,render_template,request,session,url_for

from database import get_connection,hash_password,set_user_active,validate_password
from services import require_permission

crud=Blueprint("crud",__name__,url_prefix="/manage")

ACTION={
 "supplier":"suppliers","customer":"customers","purchase":"purchases","expense":"expenses","labour":"labour",
 "batch":"production","production":"production","harvest":"harvest","sale":"sales","material":"raw_materials",
 "usage":"raw_materials","adjustment":"raw_materials","stock_adjustment":"stock","payment":"payments","user":"users"}
LIST_ENDPOINT={"supplier":"suppliers_web","customer":"customers_web","purchase":"purchases_web","expense":"expenses_web","labour":"labour_web","batch":"production","production":"production","harvest":"harvest","sale":"sales","material":"raw_materials_web","usage":"raw_materials_web","adjustment":"raw_materials_web","stock_adjustment":"stock","payment":"payments_web","user":"users_web"}

def allowed(action):
    if not session.get("user"):return False
    try:require_permission(session["user"]["role"],action);return True
    except PermissionError:return False

def guard(resource,operation):
    if not session.get("user"):return redirect(url_for("login"))
    action=f"{ACTION[resource]}.{operation}"
    if not allowed(action):return "Forbidden",403

def opts(sql):
    with get_connection() as c:return [(str(r[0]),str(r[1])) for r in c.execute(sql)]

def definition(resource):
    choices={
      "supplier":[],"customer":[],
      "purchase":[("supplier_id","Supplier","select",opts("SELECT id,name FROM suppliers ORDER BY name")),("material_id","Raw Material","select",opts("SELECT id,item FROM raw_materials ORDER BY item")),("batch_no","Batch","select",[("","Not linked")]+opts("SELECT batch_no,batch_no FROM batches ORDER BY batch_no"))],
      "production":[("batch_id","Batch","select",opts("SELECT id,batch_no FROM batches ORDER BY batch_no"))],
      "harvest":[("batch_id","Batch","select",opts("SELECT id,batch_no FROM batches ORDER BY batch_no"))],
      "sale":[("customer_id","Customer","select",[("","Cash Customer")]+opts("SELECT id,name FROM customers ORDER BY name")),("batch_id","Exact Batch","select",opts("SELECT id,batch_no FROM batches ORDER BY batch_no"))],
      "usage":[("material_id","Raw Material","select",opts("SELECT id,item FROM raw_materials ORDER BY item")),("batch_id","Batch","select",[("","Unallocated")]+opts("SELECT id,batch_no FROM batches ORDER BY batch_no"))],
      "adjustment":[("material_id","Raw Material","select",opts("SELECT id,item FROM raw_materials ORDER BY item")),("batch_id","Batch","select",[("","Unallocated")]+opts("SELECT id,batch_no FROM batches ORDER BY batch_no"))],
    }
    base={
      "supplier":[("name","Name","text",None),("mobile","Mobile","text",None),("email","Email","email",None),("address","Address","text",None),("opening_due","Opening Due","number",None),("notes","Notes","text",None)],
      "customer":[("name","Name","text",None),("mobile","Mobile","text",None),("email","Email","email",None),("address","Address","text",None),("opening_due","Opening Balance","number",None),("notes","Notes","text",None)],
      "purchase":[("purchase_date","Date","date",None),("purchase_invoice","Invoice No","text",None)]+choices["purchase"]+[("quantity","Quantity","number",None),("unit","Unit","select",[(x,x) for x in ("Kg","Gram","Bag","Piece","Litre")]),("rate","Rate","number",None),("paid_amount","Paid","number",None),("payment_mode","Payment Mode","select",[(x,x) for x in ("Cash","Bank","UPI","Credit","Other")]),("notes","Notes","text",None)],
      "expense":[("expense_date","Date","date",None),("category","Category","text",None),("description","Description","text",None),("amount","Amount","number",None),("payment_mode","Payment Mode","select",[(x,x) for x in ("Cash","Bank","UPI","Other")]),("batch_no","Batch No","text",None),("notes","Notes","text",None)],
      "labour":[("worker_name","Worker","text",None),("work_date","Date","date",None),("work_type","Work Type","text",None),("batch_no","Batch No","text",None),("days","Days","number",None),("hours","Hours","number",None),("rate","Rate","number",None),("paid","Paid","number",None),("payment_mode","Payment Mode","select",[(x,x) for x in ("Cash","Bank","UPI","Other")]),("notes","Notes","text",None)],
      "batch":[("batch_no","Batch No","text",None),("production_date","Start Date","date",None),("straw_type","Straw Type","text",None),("straw_qty","Straw Kg","number",None),("spawn_qty","Spawn Kg","number",None),("bag_count","Bags","number",None),("bag_size","Bag Size Kg","number",None),("expected_yield","Expected Yield Kg","number",None),("expected_harvest_date","Expected Harvest","date",None),("room_rack","Room / Rack","text",None),("status","Status","select",[(x,x) for x in ("Preparing","Growing","Harvesting","Completed","Failed")]),("notes","Notes","text",None)],
      "production":[("production_date","Date","date",None)]+choices["production"]+[("bags","Bags","number",None),("production_kg","Production Kg","number",None),("wastage_kg","Wastage Kg","number",None),("room_rack","Room / Rack","text",None),("notes","Notes","text",None)],
      "harvest":[("harvest_date","Date","date",None)]+choices["harvest"]+[("flush_no","Flush","select",[(str(x),str(x)) for x in range(1,5)]),("quantity_kg","Harvest Kg","number",None),("wastage_kg","Wastage Kg","number",None),("grade","Grade","select",[(x,x) for x in ("A","B","C")]),("notes","Notes","text",None)],
      "sale":[("sale_date","Date","date",None)]+choices["sale"]+[("quantity_kg","Quantity Kg","number",None),("rate_per_kg","Rate/Kg","number",None),("discount","Discount","number",None),("paid_amount","Paid","number",None),("payment_mode","Payment Mode","select",[(x,x) for x in ("Cash","Bank","UPI","Credit")]),("notes","Notes","text",None)],
      "material":[("item","Material","text",None),("unit","Unit","select",[(x,x) for x in ("Kg","Gram","Bag","Piece","Litre")]),("opening_stock","Opening Stock","number",None),("reorder_level","Reorder Level","number",None)],
      "usage":[("usage_date","Date","date",None)]+choices["usage"]+[("quantity","Quantity","number",None),("notes","Notes","text",None)],
      "adjustment":[("adjustment_date","Date","date",None)]+choices["adjustment"]+[("adjustment_type","Type","select",[("IN","Adjustment In"),("OUT","Adjustment Out")]),("quantity","Quantity","number",None),("notes","Notes","text",None)],
      "stock_adjustment":[("transaction_date","Date","date",None),("transaction_type","Type","select",[("ADJUSTMENT IN","Adjustment In"),("ADJUSTMENT OUT","Adjustment Out"),("OPENING STOCK","Opening Stock")]),("batch_no","Batch No","text",None),("quantity_kg","Quantity Kg","number",None),("notes","Notes","text",None)],
      "payment":[("payment_date","Date","date",None),("party","Party","select",[(f"CUSTOMER PAYMENT|{i}",f"Customer — {n}") for i,n in opts("SELECT id,name FROM customers ORDER BY name")]+[(f"SUPPLIER PAYMENT|{i}",f"Supplier — {n}") for i,n in opts("SELECT id,name FROM suppliers ORDER BY name")]+[(f"LABOUR PAYMENT|{i}",f"Labour — {n}") for i,n in opts("SELECT id,worker_name FROM labour ORDER BY worker_name")]),("amount","Amount","number",None),("payment_mode","Mode","select",[(x,x) for x in ("Cash","Bank","UPI")]),("reference","Reference","text",None),("notes","Notes","text",None)],
      "user":[("username","Username","text",None),("full_name","Full Name","text",None),("password","Password","password",None),("role","Role","select",[(x,x) for x in ("ADMIN","MANAGER","STAFF")])]
    }
    return base[resource]

TABLE={"supplier":"suppliers","customer":"customers","purchase":"purchases","expense":"expenses","labour":"labour","batch":"batches","production":"daily_production","harvest":"harvests","sale":"sales","material":"raw_materials","usage":"material_usage","adjustment":"material_adjustments","stock_adjustment":"stock_transactions","user":"users"}

def existing(resource,record_id,fields):
    if not record_id:return {}
    if resource=="payment":
        with get_connection() as c:
            row=c.execute("SELECT transaction_date,source_table,source_id,debit,credit,payment_mode,reference,notes FROM cash_ledger WHERE id=?",(record_id,)).fetchone()
        if not row:raise ValueError("Payment not found")
        types={"customer_payments":"CUSTOMER PAYMENT","supplier_payments":"SUPPLIER PAYMENT","labour_payments":"LABOUR PAYMENT"}
        return {"payment_date":row[0],"party":f"{types.get(row[1],'')}|{row[2]}","amount":row[4] if row[4] else row[3],"payment_mode":row[5],"reference":row[6] or "","notes":row[7] or ""}
    names=[x[0] for x in fields if not (resource=="user" and x[0]=="password")]
    with get_connection() as c:row=c.execute(f"SELECT {','.join(names)} FROM {TABLE[resource]} WHERE id=?",(record_id,)).fetchone()
    if not row:raise ValueError("Record not found")
    data=dict(zip(names,row))
    if resource=="stock_adjustment":data["quantity_kg"]=abs(float(data["quantity_kg"] or 0))
    return data

def form_data(fields):
    data={}
    for name,label,kind,options in fields:
        raw=request.form.get(name,"").strip()
        if kind=="number":data[name]=float(raw or 0)
        elif name.endswith("_id") or name=="party_id":data[name]=int(raw) if raw else None
        else:data[name]=raw
    return data

def save(resource,data,record_id):
    from services import save_party,save_purchase,save_expense,save_labour,save_batch,save_production,save_harvest,save_sale,save_material,save_material_usage,save_material_adjustment,save_stock_adjustment,generate_invoice_no
    if resource in ("supplier","customer"):return save_party(resource,data,record_id)
    if resource=="purchase":return save_purchase(data,record_id)
    if resource=="expense":return save_expense(data,record_id)
    if resource=="labour":return save_labour(data,record_id)
    if resource=="batch":return save_batch(data,record_id)
    if resource=="production":return save_production(data,record_id)
    if resource=="harvest":return save_harvest(data,record_id)
    if resource=="sale":
        if record_id:
            with get_connection() as c:data["invoice_no"]=c.execute("SELECT invoice_no FROM sales WHERE id=?",(record_id,)).fetchone()[0]
        else:data["invoice_no"]=generate_invoice_no()
        return save_sale(data,record_id)
    if resource=="material":return save_material(data,record_id)
    if resource=="usage":return save_material_usage(data,record_id)
    if resource=="adjustment":return save_material_adjustment(data,record_id)
    if resource=="stock_adjustment":return save_stock_adjustment(data,record_id)
    if resource=="payment":
        from modules.accounts import record_payment,update_payment
        payment_type,party_id=data["party"].split("|",1)
        args=(data["payment_date"],payment_type,int(party_id),data["amount"],data["payment_mode"],data["reference"],data["notes"])
        return update_payment(record_id,*args) if record_id else record_payment(*args)
    if resource=="user":
        if record_id:raise ValueError("Use account status/reset actions for existing users")
        validate_password(data["password"])
        with get_connection() as c:return c.execute("INSERT INTO users(username,full_name,password_hash,role) VALUES(?,?,?,?)",(data["username"],data["full_name"],hash_password(data["password"]),data["role"])).lastrowid

def remove(resource,record_id):
    from services import delete_party,delete_source_record,delete_batch,delete_production,delete_harvest,delete_sale,delete_material,delete_material_usage,delete_material_adjustment,delete_stock_adjustment
    if resource in ("supplier","customer"):return delete_party(resource,record_id)
    if resource in ("purchase","expense","labour"):return delete_source_record(TABLE[resource],record_id)
    if resource=="batch":return delete_batch(record_id)
    if resource=="production":return delete_production(record_id)
    if resource=="harvest":return delete_harvest(record_id)
    if resource=="sale":return delete_sale(record_id)
    if resource=="material":return delete_material(record_id)
    if resource=="usage":return delete_material_usage(record_id)
    if resource=="adjustment":return delete_material_adjustment(record_id)
    if resource=="stock_adjustment":return delete_stock_adjustment(record_id)
    if resource=="payment":
        from modules.accounts import delete_payment
        return delete_payment(record_id)

@crud.route("/<resource>/new",methods=["GET","POST"])
@crud.route("/<resource>/<int:record_id>/edit",methods=["GET","POST"])
def resource_form(resource,record_id=None):
    if resource not in ACTION:return "Not found",404
    denied=guard(resource,"edit" if record_id else "create")
    if denied:return denied
    fields=definition(resource)
    try:
        values=existing(resource,record_id,fields)
        if request.method=="POST":
            save(resource,form_data(fields),record_id);flash("Record saved.","success");return redirect(url_for(LIST_ENDPOINT[resource]))
    except (ValueError,OverflowError,sqlite3.Error,KeyError,TypeError) as error:flash(str(error),"error")
    return render_template("crud_form.html",title=("Edit " if record_id else "+ New ")+resource.replace("_"," ").title(),resource=resource,fields=fields,values=values,record_id=record_id)

@crud.route("/<resource>/<int:record_id>/delete",methods=["POST"])
def resource_delete(resource,record_id):
    if resource not in ACTION:return "Not found",404
    denied=guard(resource,"delete")
    if denied:return denied
    try:remove(resource,record_id);flash("Record deleted.","success")
    except (ValueError,OverflowError,sqlite3.Error,PermissionError) as error:flash(str(error),"error")
    return redirect(url_for(LIST_ENDPOINT[resource]))

@crud.route("/<kind>/<int:record_id>/statement")
def statement(kind,record_id):
    if kind not in ("customer","supplier"):return "Not found",404
    denied=guard(kind,"view")
    if denied:return denied
    from services import customer_statement,supplier_statement
    opening,rows=(customer_statement if kind=="customer" else supplier_statement)(record_id,request.args.get("start"),request.args.get("end"))
    return render_template("statement_web.html",title=kind.title()+" Statement",opening=opening,rows=rows)

@crud.route("/user/<int:record_id>/toggle",methods=["POST"])
def user_toggle(record_id):
    denied=guard("user","edit")
    if denied:return denied
    try:
        with get_connection() as c:row=c.execute("SELECT active FROM users WHERE id=?",(record_id,)).fetchone()
        if not row:raise ValueError("User not found")
        set_user_active(record_id,not bool(row[0]));flash("User status updated.","success")
    except ValueError as error:flash(str(error),"error")
    return redirect(url_for("users_web"))

@crud.route("/user/<int:record_id>/reset",methods=["GET","POST"])
def user_reset(record_id):
    denied=guard("user","edit")
    if denied:return denied
    if request.method=="POST":
        from database import admin_reset_password
        try:admin_reset_password(session["user"]["id"],record_id,request.form.get("password",""));flash("Temporary password saved; user must change it on next login.","success");return redirect(url_for("users_web"))
        except (ValueError,PermissionError) as error:flash(str(error),"error")
    return render_template("user_reset.html",title="Reset User Password",record_id=record_id)

@crud.app_context_processor
def helpers():return {"can":allowed}
