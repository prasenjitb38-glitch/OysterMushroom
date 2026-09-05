import tkinter as tk
from datetime import date
from tkinter import ttk,messagebox
from database import get_connection
from modules.crud import CrudPage
from services import save_expense, save_purchase, save_labour, delete_source_record,raw_material_stock,save_material_usage,delete_material_usage,save_material_adjustment,delete_material_adjustment


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
        ("payment_mode","Payment Mode","choice",("Cash","UPI","Bank","Other")),("notes","Notes","text",())),"work_date",labour_compute,saver=save_labour,deleter=lambda i:delete_source_record("labour",i))


class ExpensePage(CrudPage):
    def __init__(self,parent): super().__init__(parent,"Expense Management","expenses",(
        ("expense_date","Date","text",()),("category","Category","text",()),("description","Description","text",()),("amount","Amount","number",()),
        ("payment_mode","Payment Mode","choice",("Cash","UPI","Bank","Other")),("batch_no","Batch No","text",()),("notes","Notes","text",())),"expense_date",saver=save_expense,deleter=lambda i:delete_source_record("expenses",i))


class PurchasePage(CrudPage):
    def __init__(self,parent): super().__init__(parent,"Purchase Management","purchases",(
        ("purchase_date","Date","text",()),("purchase_invoice","Invoice","text",()),("supplier_id","Supplier ID","number",()),("material_id","Material ID","number",()),
        ("quantity","Quantity","number",()),("unit","Unit","choice",("Kg","Gram","Bag","Piece","Litre")),("rate","Rate","number",()),
        ("total_amount","Total","number",()),("paid_amount","Paid","number",()),("due_amount","Due","number",()),("batch_no","Batch No","text",()),
        ("payment_mode","Payment Mode","choice",("Cash","UPI","Bank","Other","Credit")),("notes","Notes","text",())),"purchase_date",purchase_compute,saver=save_purchase,deleter=lambda i:delete_source_record("purchases",i))


class RawMaterialPage:
    def __init__(self,parent):self.parent=parent;self.frame=tk.Frame(parent,bg="#f5f6fa");self.build();self.load()
    def build(self):
        top=tk.Frame(self.frame,bg="#f5f6fa");top.pack(fill="x",padx=20,pady=12);tk.Label(top,text="🧪 Raw Material Management",font=("Arial",22,"bold"),bg="#f5f6fa").pack(side="left")
        for text,cmd in (("➕ Usage",lambda:self.tx_form("usage")),("Adjustment In",lambda:self.tx_form("IN")),("Adjustment Out",lambda:self.tx_form("OUT")),("🔄 Refresh",self.load)):tk.Button(top,text=text,command=cmd).pack(side="right",padx=3)
        book=ttk.Notebook(self.frame);book.pack(fill="both",expand=True,padx=20,pady=8);tabs=[]
        for title in ("Current Stock","Usage History","Adjustment History","Batch Consumption"):f=tk.Frame(book);book.add(f,text=title);tabs.append(f)
        self.stock=self.table(tabs[0],("ID","Material","Unit","Opening","Purchased","Used","Adjustment","Current","Minimum","Status"));self.usage=self.table(tabs[1],("ID","Date","Material","Batch","Quantity","Unit","Notes"));self.adjust=self.table(tabs[2],("ID","Date","Material","Type","Quantity","Batch","Notes"));self.batch=self.table(tabs[3],("Batch","Material","Quantity","Unit"))
        actions=tk.Frame(self.frame,bg="#f5f6fa");actions.pack(fill="x",padx=20,pady=5);tk.Button(actions,text="Edit Selected Usage",command=lambda:self.edit_selected("usage")).pack(side="left");tk.Button(actions,text="Delete Selected Usage",command=lambda:self.remove_selected("usage")).pack(side="left",padx=4);tk.Button(actions,text="Edit Selected Adjustment",command=lambda:self.edit_selected("adjust")).pack(side="left");tk.Button(actions,text="Delete Selected Adjustment",command=lambda:self.remove_selected("adjust")).pack(side="left",padx=4)
    def table(self,parent,cols):
        t=ttk.Treeview(parent,columns=cols,show="headings");[t.heading(c,text=c) for c in cols];t.pack(fill="both",expand=True);return t
    def load(self):
        for t in (self.stock,self.usage,self.adjust,self.batch):
            for x in t.get_children():t.delete(x)
        with get_connection() as c:
            materials=c.execute("SELECT id,item,unit,opening_stock,reorder_level FROM raw_materials ORDER BY item").fetchall()
            for mid,name,unit,opening,minimum in materials:
                purchased=c.execute("SELECT COALESCE(SUM(quantity),0) FROM purchases WHERE material_id=?",(mid,)).fetchone()[0];used=c.execute("SELECT COALESCE(SUM(quantity),0) FROM material_usage WHERE material_id=?",(mid,)).fetchone()[0];adj=c.execute("SELECT COALESCE(SUM(CASE WHEN adjustment_type='IN' THEN quantity ELSE -quantity END),0) FROM material_adjustments WHERE material_id=?",(mid,)).fetchone()[0];current=raw_material_stock(mid,c);self.stock.insert("","end",values=(mid,name,unit,opening,purchased,used,adj,f"{current:.2f}",minimum,"LOW STOCK" if current<=minimum else "OK"))
            for r in c.execute("SELECT u.id,u.usage_date,m.item,COALESCE(b.batch_no,''),u.quantity,m.unit,COALESCE(u.notes,'') FROM material_usage u JOIN raw_materials m ON m.id=u.material_id LEFT JOIN batches b ON b.id=u.batch_id ORDER BY u.id DESC"):self.usage.insert("","end",values=r)
            for r in c.execute("SELECT a.id,a.adjustment_date,m.item,a.adjustment_type,a.quantity,COALESCE(b.batch_no,''),COALESCE(a.notes,'') FROM material_adjustments a JOIN raw_materials m ON m.id=a.material_id LEFT JOIN batches b ON b.id=a.batch_id ORDER BY a.id DESC"):self.adjust.insert("","end",values=r)
            for r in c.execute("SELECT COALESCE(b.batch_no,'Unallocated'),m.item,SUM(u.quantity),m.unit FROM material_usage u JOIN raw_materials m ON m.id=u.material_id LEFT JOIN batches b ON b.id=u.batch_id GROUP BY b.id,m.id"):self.batch.insert("","end",values=r)
    def tx_form(self,kind,record_id=None):
        with get_connection() as c:mats=c.execute("SELECT id,item,unit FROM raw_materials ORDER BY item").fetchall();batches=c.execute("SELECT id,batch_no FROM batches ORDER BY batch_no").fetchall();old=c.execute("SELECT usage_date,material_id,batch_id,quantity,notes FROM material_usage WHERE id=?",(record_id,)).fetchone() if record_id and kind=="usage" else (c.execute("SELECT adjustment_date,material_id,batch_id,quantity,notes,adjustment_type FROM material_adjustments WHERE id=?",(record_id,)).fetchone() if record_id else None)
        w=tk.Toplevel(self.parent);w.title("Material Usage" if kind=="usage" else "Material Adjustment");w.geometry("420x420");body=tk.Frame(w);body.pack(fill="x",padx=30,pady=15)
        tk.Label(body,text="Date").pack(anchor="w");dt=tk.Entry(body);dt.insert(0,old[0] if old else date.today().isoformat());dt.pack(fill="x");tk.Label(body,text="Material").pack(anchor="w");mat=ttk.Combobox(body,values=[m[1] for m in mats],state="readonly");mat.pack(fill="x");mat.current([m[0] for m in mats].index(old[1]) if old else 0);tk.Label(body,text="Batch (optional)").pack(anchor="w");batch=ttk.Combobox(body,values=["Unallocated"]+[b[1] for b in batches],state="readonly");batch.pack(fill="x");batch.current(([b[0] for b in batches].index(old[2])+1) if old and old[2] in [b[0] for b in batches] else 0);tk.Label(body,text="Quantity").pack(anchor="w");qty=tk.Entry(body);qty.insert(0,str(old[3]) if old else "");qty.pack(fill="x");tk.Label(body,text="Notes").pack(anchor="w");notes=tk.Entry(body);notes.insert(0,old[4] or "" if old else "");notes.pack(fill="x")
        def save():
            try:
                data={"material_id":mats[mat.current()][0],"batch_id":batches[batch.current()-1][0] if batch.current()>0 else None,"quantity":float(qty.get()),"notes":notes.get()}
                if kind=="usage":data["usage_date"]=dt.get();save_material_usage(data,record_id)
                else:data.update(adjustment_date=dt.get(),adjustment_type=kind if not old else old[5]);save_material_adjustment(data,record_id)
                w.destroy();self.load()
            except (ValueError,OverflowError,IndexError) as e:messagebox.showerror("Error",str(e),parent=w)
        tk.Button(body,text="Save",command=save,bg="#27ae60",fg="white").pack(pady=18)
    def selected(self,tree):
        s=tree.selection();return int(tree.item(s[0],"values")[0]) if s else None
    def edit_selected(self,kind):
        i=self.selected(self.usage if kind=="usage" else self.adjust)
        if i:self.tx_form(kind,i)
    def remove_selected(self,kind):
        i=self.selected(self.usage if kind=="usage" else self.adjust)
        if not i:return
        try:(delete_material_usage if kind=="usage" else delete_material_adjustment)(i);self.load()
        except OverflowError as e:messagebox.showerror("Cannot Delete",str(e),parent=self.frame)
    def show(self):self.frame.pack(fill="both",expand=True)
