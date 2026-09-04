from modules.crud import CrudPage


def labour_compute(d):
    d["amount"]=(d["days"]*d["rate"]) if d["days"]>0 else (d["hours"]*d["rate"])
    if d["paid"]>d["amount"]: raise ValueError
    return {"amount":d["amount"]}


def purchase_compute(d):
    total=d["quantity"]*d["rate"]
    if d["paid_amount"]>total: raise ValueError
    return {"total_amount":total,"due_amount":total-d["paid_amount"]}


class LabourPage(CrudPage):
    def __init__(self,parent): super().__init__(parent,"Labour Management","labour",(
        ("worker_name","Worker","text",()),("work_date","Date","text",()),("work_type","Work Type","text",()),("batch_no","Batch No","text",()),
        ("days","Days","number",()),("hours","Hours","number",()),("rate","Rate","number",()),("amount","Amount","number",()),("paid","Paid","number",()),
        ("payment_mode","Payment Mode","choice",("Cash","UPI","Bank","Other")),("notes","Notes","text",())),"work_date",labour_compute)


class ExpensePage(CrudPage):
    def __init__(self,parent): super().__init__(parent,"Expense Management","expenses",(
        ("expense_date","Date","text",()),("category","Category","text",()),("description","Description","text",()),("amount","Amount","number",()),
        ("payment_mode","Payment Mode","choice",("Cash","UPI","Bank","Other")),("batch_no","Batch No","text",()),("notes","Notes","text",())),"expense_date")


class PurchasePage(CrudPage):
    def __init__(self,parent): super().__init__(parent,"Purchase Management","purchases",(
        ("purchase_date","Date","text",()),("purchase_invoice","Invoice","text",()),("supplier_id","Supplier ID","number",()),("item","Item","text",()),
        ("quantity","Quantity","number",()),("unit","Unit","choice",("Kg","Gram","Bag","Piece","Litre")),("rate","Rate","number",()),
        ("total_amount","Total","number",()),("paid_amount","Paid","number",()),("due_amount","Due","number",()),("batch_no","Batch No","text",()),
        ("payment_mode","Payment Mode","choice",("Cash","UPI","Bank","Other","Credit")),("notes","Notes","text",())),"purchase_date",purchase_compute)


class RawMaterialPage(CrudPage):
    def __init__(self,parent): super().__init__(parent,"Raw Materials","raw_materials",(
        ("item","Item","text",()),("unit","Unit","choice",("Kg","Gram","Bag","Piece","Litre")),
        ("opening_stock","Opening Stock","number",()),("reorder_level","Reorder Level","number",())))
