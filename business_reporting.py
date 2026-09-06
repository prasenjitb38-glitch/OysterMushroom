import csv
import io
from datetime import date, datetime, timedelta

from database import get_connection
from capital_service import capital_register, capital_summary
from services import (
    batch_cost_rows, cash_balance, customer_outstanding, labour_due,
    mushroom_stock, pnl, raw_material_stock, supplier_outstanding,
)


def money(value):
    value=float(value or 0)
    return ("-" if value<0 else "")+"₹"+f"{abs(value):,.2f}"


def quantity(value):
    return f"{float(value or 0):,.2f} Kg"


def resolve_dates(start=None,end=None,quick=None):
    today=date.today()
    quick=(quick or "").lower()
    if quick=="today":start=end=today.isoformat()
    elif quick=="month":start=today.replace(day=1).isoformat();end=today.isoformat()
    elif quick=="fy":
        year=today.year if today.month>=4 else today.year-1
        start=date(year,4,1).isoformat();end=today.isoformat()
    if not start or not end:
        with get_connection() as c:
            row=c.execute("""SELECT MIN(d),MAX(d) FROM (
                SELECT sale_date d FROM sales UNION ALL SELECT purchase_date FROM purchases
                UNION ALL SELECT expense_date FROM expenses UNION ALL SELECT production_date FROM daily_production
                UNION ALL SELECT harvest_date FROM harvests UNION ALL SELECT date FROM owner_capital)
                WHERE COALESCE(d,'')<>''""").fetchone()
        start=start or row[0] or today.isoformat();end=end or row[1] or today.isoformat()
    try:
        a=datetime.strptime(start,"%Y-%m-%d").date();b=datetime.strptime(end,"%Y-%m-%d").date()
    except (TypeError,ValueError):
        raise ValueError("Dates must use YYYY-MM-DD format.")
    if a>b:raise ValueError("From date cannot be after To date.")
    if (b-a).days>3660:raise ValueError("Select a date range of 10 years or less.")
    return a.isoformat(),b.isoformat()


def _rows(conn,sql,start,end):
    return [tuple(r) for r in conn.execute(sql,(start,end)).fetchall()]


def report_view_model(start=None,end=None,quick=None):
    start,end=resolve_dates(start,end,quick)
    with get_connection() as c:
        sales=_rows(c,"""SELECT s.sale_date,s.invoice_no,COALESCE(c.name,'Cash Customer'),s.quantity_kg,
            s.total_amount,s.paid_amount,s.total_amount-s.paid_amount FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
            WHERE s.sale_date BETWEEN ? AND ? ORDER BY s.sale_date DESC,s.id DESC""",start,end)
        purchases=_rows(c,"""SELECT p.purchase_date,COALESCE(p.purchase_invoice,''),COALESCE(s.name,''),p.item,p.quantity,p.unit,
            p.total_amount,p.paid_amount,p.due_amount FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id
            WHERE p.purchase_date BETWEEN ? AND ? ORDER BY p.purchase_date DESC,p.id DESC""",start,end)
        production=_rows(c,"SELECT production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg FROM daily_production WHERE production_date BETWEEN ? AND ? ORDER BY production_date DESC,id DESC",start,end)
        harvest=_rows(c,"SELECT harvest_date,batch_no,flush_no,quantity_kg,wastage_kg,quantity_kg-wastage_kg,grade FROM harvests WHERE harvest_date BETWEEN ? AND ? ORDER BY harvest_date DESC,id DESC",start,end)
        expenses=_rows(c,"SELECT expense_date,category,description,amount,payment_mode,batch_no FROM expenses WHERE expense_date BETWEEN ? AND ? ORDER BY expense_date DESC,id DESC",start,end)
        materials=[(r[1],r[2],raw_material_stock(r[0],c),r[3]) for r in c.execute("SELECT id,item,unit,reorder_level FROM raw_materials ORDER BY item")]
        stock=_rows(c,"""SELECT d,kind,batch,qty FROM (
            SELECT harvest_date d,'Harvest In' kind,batch_no batch,quantity_kg-wastage_kg qty FROM harvests
            UNION ALL SELECT sale_date,'Sales Out',batch_no,-quantity_kg FROM sales
            UNION ALL SELECT transaction_date,transaction_type,batch_no,quantity_kg FROM stock_transactions)
            WHERE d BETWEEN ? AND ? ORDER BY d DESC""",start,end)
        customer_dues=[(r[0],customer_outstanding(r[1],c)) for r in c.execute("SELECT name,id FROM customers ORDER BY name")]
        supplier_dues=[(r[0],supplier_outstanding(r[1],c)) for r in c.execute("SELECT name,id FROM suppliers ORDER BY name")]
        labour_dues=[(r[0],r[1]-r[2]-r[3]) for r in c.execute("""SELECT l.worker_name,l.amount,l.paid,
            COALESCE((SELECT SUM(p.amount) FROM labour_payments p WHERE p.labour_id=l.id),0) FROM labour l ORDER BY l.worker_name""")]
        capital_rows=[tuple(r[1:]) for r in capital_register(start,end,c)]
        capital=capital_summary(c)
        sales_total=sum(r[4] for r in sales);purchase_total=sum(r[6] for r in purchases);expense_total=sum(r[3] for r in expenses)
        saleable=sum(r[5] for r in production);harvest_saleable=sum(r[5] for r in harvest);wastage=sum(r[4] for r in harvest)+sum(r[4] for r in production)
        batches=[]
        for row in batch_cost_rows(start,end):
            revenue=c.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE batch_no=? AND sale_date BETWEEN ? AND ?",(row[0],start,end)).fetchone()[0]
            batches.append((row[0],row[6],row[5],row[8],revenue,revenue-row[6]))
    profit=pnl(start,end)
    cash=cash_balance("Cash");bank=cash_balance("Bank")
    sections=[
        ("Sales",("Date","Invoice","Customer","Qty","Total","Paid","Due"),sales),
        ("Purchases",("Date","Invoice","Supplier","Material","Qty","Unit","Total","Paid","Due"),purchases),
        ("Production",("Date","Batch","Bags","Production","Wastage","Saleable"),production),
        ("Harvest",("Date","Batch","Flush","Harvest","Wastage","Saleable","Grade"),harvest),
        ("Expenses",("Date","Category","Description","Amount","Mode","Batch"),expenses),
        ("Raw Material Stock",("Material","Unit","Stock","Reorder Level"),materials),
        ("Mushroom Stock Reconciliation",("Date","Movement","Batch","Quantity"),stock),
        ("Customer Due",("Customer","Due"),[r for r in customer_dues if r[1]>0]),
        ("Supplier Due",("Supplier","Due"),[r for r in supplier_dues if r[1]>0]),
        ("Labour Due",("Worker","Due"),[r for r in labour_dues if r[1]>0]),
        ("Cash / Bank",("Account","Available"),[("Cash",cash),("Bank",bank),("Total",cash+bank)]),
        ("Capital Report",("Date","Type","Reference","Cash","Bank","Total","Notes"),capital_rows),
        ("Profit Summary",("Sales","COGS","Gross","Expenses","Net","Margin %"),[tuple(profit[k] for k in ("sales","cogs","gross","expenses","net","margin"))]),
        ("Batch Report",("Batch","Total Cost","Harvest","Cost/Kg","Sales","P/L"),batches),
    ]
    assets=cash+bank+customer_outstanding()
    liabilities=supplier_outstanding()+labour_due()
    equity=capital["closing"]+profit["net"]
    sections.append(("Balance Sheet Foundation",("Section","Account","Amount"),[
        ("Assets","Cash",cash),("Assets","Bank",bank),
        ("Assets","Customer Receivables",customer_outstanding()),
        ("Liabilities","Supplier Due",supplier_outstanding()),
        ("Liabilities","Labour Due",labour_due()),
        ("Equity","Owner Capital (net of drawings)",capital["closing"]),
        ("Equity","Current Tested P&L",profit["net"]),
        ("Reconciliation","Assets - Liabilities - Equity (unclassified gap)",assets-liabilities-equity),
    ]))
    summary=[
        ("Sales",money(sales_total)),("Purchases",money(purchase_total)),("Expenses",money(expense_total)),("Net Profit",money(profit["net"])),
        ("Production",quantity(sum(r[3] for r in production))),("Saleable Harvest",quantity(harvest_saleable)),("Mushroom Stock",quantity(mushroom_stock())),("Wastage",quantity(wastage)),
        ("Customer Due",money(customer_outstanding())),("Supplier Due",money(supplier_outstanding())),("Labour Due",money(labour_due())),
        ("Cash",money(cash)),("Bank",money(bank)),("Total Available",money(cash+bank)),
        ("Closing Owner Capital",money(capital["closing"])),
    ]
    return {"start":start,"end":end,"summary":summary,"sections":sections,"profit":profit}


def _bucket_expression(column,period):
    if period=="Daily":return column
    if period=="Monthly":return f"substr({column},1,7)"
    if period=="Yearly":return f"substr({column},1,4)"
    raise ValueError("Period must be Daily, Monthly, or Yearly.")


def _series(conn,table,date_col,value_sql,start,end,period):
    bucket=_bucket_expression(date_col,period)
    return {r[0]:float(r[1] or 0) for r in conn.execute(
        f"SELECT {bucket},COALESCE(SUM({value_sql}),0) FROM {table} WHERE {date_col} BETWEEN ? AND ? GROUP BY {bucket} ORDER BY {bucket}",
        (start,end))}


def chart_view_model(start=None,end=None,period="Daily"):
    start,end=resolve_dates(start,end)
    if period not in ("Daily","Monthly","Yearly"):raise ValueError("Period must be Daily, Monthly, or Yearly.")
    with get_connection() as c:
        sales=_series(c,"sales","sale_date","total_amount",start,end,period)
        sold=_series(c,"sales","sale_date","quantity_kg",start,end,period)
        production=_series(c,"daily_production","production_date","production_kg",start,end,period)
        harvest=_series(c,"harvests","harvest_date","quantity_kg-wastage_kg",start,end,period)
        bucket=_bucket_expression("transaction_date",period)
        excluded=("OPENING CAPITAL","CAPITAL INTRODUCED","DRAWINGS")
        income={r[0]:float(r[1] or 0) for r in c.execute(
            f"""SELECT {bucket},COALESCE(SUM(credit),0) FROM cash_ledger
            WHERE transaction_date BETWEEN ? AND ? AND transaction_type NOT IN (?,?,?)
            GROUP BY {bucket} ORDER BY {bucket}""",(start,end)+excluded)}
        expense={r[0]:float(r[1] or 0) for r in c.execute(
            f"""SELECT {bucket},COALESCE(SUM(debit),0) FROM cash_ledger
            WHERE transaction_date BETWEEN ? AND ? AND transaction_type NOT IN (?,?,?)
            GROUP BY {bucket} ORDER BY {bucket}""",(start,end)+excluded)}
        harvest_in=harvest
        adjustments=_series(c,"stock_transactions","transaction_date","quantity_kg",start,end,period)
        opening=float(c.execute("SELECT COALESCE((SELECT value FROM settings WHERE key='opening_mushroom_stock'),'0')").fetchone()[0] or 0)
        prior_harvest=c.execute("SELECT COALESCE(SUM(quantity_kg-wastage_kg),0) FROM harvests WHERE harvest_date<?",(start,)).fetchone()[0]
        prior_adjustments=c.execute("SELECT COALESCE(SUM(quantity_kg),0) FROM stock_transactions WHERE transaction_date<?",(start,)).fetchone()[0]
        prior_sales=c.execute("SELECT COALESCE(SUM(quantity_kg),0) FROM sales WHERE sale_date<?",(start,)).fetchone()[0]
        labels=sorted(set(sales)|set(production)|set(harvest)|set(income)|set(expense)|set(adjustments))
        profit_rows=[]
        for label in labels:
            if period=="Daily":a=b=label
            elif period=="Monthly":
                a=label+"-01";year,month=map(int,label.split("-"));b=(date(year+month//12,month%12+1,1)-timedelta(days=1)).isoformat()
            else:a=label+"-01-01";b=label+"-12-31"
            result=pnl(max(a,start),min(b,end));profit_rows.append((result["gross"],result["net"]))
        materials=[(r[1],raw_material_stock(r[0],c)) for r in c.execute("SELECT id,item FROM raw_materials ORDER BY item")]
        dues=[("Customer",customer_outstanding(conn=c)),("Supplier",supplier_outstanding(conn=c)),("Labour",labour_due(c))]
        costs={r[0]:r[6] for r in batch_cost_rows(start,end)}
        revenues={r[0]:r[1] for r in c.execute("SELECT COALESCE(batch_no,'Unallocated'),SUM(total_amount) FROM sales WHERE sale_date BETWEEN ? AND ? GROUP BY batch_no",(start,end))}
        batch_labels=sorted(set(costs)|set(revenues))
    closing=[];running=opening+prior_harvest+prior_adjustments-prior_sales
    for label in labels:
        running+=harvest_in.get(label,0)+adjustments.get(label,0)-sold.get(label,0);closing.append(running)
    charts=[
        ("Sales Trend",labels,[("Sales",sales,"₹")]),
        ("Production vs Saleable Harvest",labels,[("Production",production,"Kg"),("Saleable Harvest",harvest,"Kg")]),
        ("Income vs Expense",labels,[("Income",income,"₹"),("Expense",expense,"₹")]),
        ("Gross / Net Profit Trend",labels,[("Gross Profit",dict(zip(labels,[r[0] for r in profit_rows])),"₹"),("Net Profit",dict(zip(labels,[r[1] for r in profit_rows])),"₹")]),
        ("Mushroom Stock Movement",labels,[("Harvest In",harvest_in,"Kg"),("Sales Out",sold,"Kg"),("Closing",dict(zip(labels,closing)),"Kg")]),
        ("Raw Material Stock",[r[0] for r in materials],[("Stock",dict(materials),"units")]),
        ("Outstanding Due",[r[0] for r in dues],[("Due",dict(dues),"₹")]),
        ("Batch Profitability",batch_labels,[("Cost",costs,"₹"),("Revenue",revenues,"₹"),("Profit",{x:revenues.get(x,0)-costs.get(x,0) for x in batch_labels},"₹")]),
    ]
    payload=[]
    for title,chart_labels,series in charts:
        payload.append({"title":title,"labels":chart_labels,"datasets":[{"label":name,"data":[values.get(x,0) for x in chart_labels],"unit":unit} for name,values,unit in series]})
    return {"start":start,"end":end,"period":period,"empty":not labels,"charts":payload}


def report_csv(model):
    output=io.StringIO(newline="");writer=csv.writer(output)
    writer.writerow(["Business Report",model["start"],model["end"]])
    for title,headers,rows in model["sections"]:
        writer.writerow([]);writer.writerow([title]);writer.writerow(headers);writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def report_pdf(model):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    output=io.BytesIO();styles=getSampleStyleSheet()
    doc=SimpleDocTemplate(output,pagesize=landscape(A4),rightMargin=25,leftMargin=25,topMargin=25,bottomMargin=25)
    story=[Paragraph("Oyster Mushroom Business Report",styles["Title"]),Paragraph(f"{model['start']} to {model['end']}",styles["Normal"]),Spacer(1,10)]
    for title,headers,rows in model["sections"]:
        story.extend((Paragraph(title,styles["Heading2"]),Table([headers]+[[str(x if x is not None else "")[:80] for x in row] for row in rows[:200]],repeatRows=1,style=TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#157052")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("GRID",(0,0),(-1,-1),.25,colors.grey),("FONTSIZE",(0,0),(-1,-1),7),("VALIGN",(0,0),(-1,-1),"TOP")])),Spacer(1,10)))
    doc.build(story);output.seek(0);return output
