import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from database import get_connection
from modules.crud import CrudPage
from services import customer_outstanding, supplier_outstanding, labour_due, post_ledger, delete_manual_ledger,enforce_desktop
from events import publish


def record_payment(payment_date, payment_type, party_id, amount, mode, reference="", notes=""):
    enforce_desktop("payments.create")
    if amount <= 0: raise ValueError("Amount must be positive")
    mapping={"CUSTOMER PAYMENT":("customer_payments","customer_id"),"SUPPLIER PAYMENT":("supplier_payments","supplier_id"),"LABOUR PAYMENT":("labour_payments","labour_id")}
    with get_connection() as conn:
        limits={"CUSTOMER PAYMENT":customer_outstanding(party_id,conn),"SUPPLIER PAYMENT":supplier_outstanding(party_id,conn),"LABOUR PAYMENT":labour_due(conn)}
        if payment_type in limits and amount>limits[payment_type]+1e-9: raise ValueError("Payment exceeds outstanding due")
        source_table = source_id = None
        if payment_type in mapping:
            table,column=mapping[payment_type]
            source_table=table
            source_id=conn.execute(f"INSERT INTO {table}(payment_date,{column},amount,payment_mode,reference_no,notes) VALUES(?,?,?,?,?,?)",(payment_date,party_id,amount,mode,reference,notes)).lastrowid
        ledger_id=post_ledger(conn,source_table or "manual_payment",source_id or 0,payment_date,payment_type,mode,amount,payment_type in ("CUSTOMER PAYMENT","OTHER INCOME"),reference,notes)
    publish("payment_changed");return ledger_id


def delete_payment(ledger_id):
    enforce_desktop("payments.delete")
    with get_connection() as conn:
        row=conn.execute("SELECT source_table,source_id FROM cash_ledger WHERE id=?",(ledger_id,)).fetchone()
        if not row: return False
        if row[0] in ("customer_payments","supplier_payments","labour_payments") and row[1] is not None:
            conn.execute(f"DELETE FROM {row[0]} WHERE id=?",(row[1],))
        conn.execute("DELETE FROM cash_ledger WHERE id=?",(ledger_id,))
    publish("payment_changed");return True


def update_payment(ledger_id, payment_date, payment_type, party_id, amount, mode, reference="", notes=""):
    enforce_desktop("payments.edit")
    if amount <= 0: raise ValueError("Amount must be positive")
    mapping={"CUSTOMER PAYMENT":("customer_payments","customer_id"),"SUPPLIER PAYMENT":("supplier_payments","supplier_id"),"LABOUR PAYMENT":("labour_payments","labour_id")}
    with get_connection() as conn:
        old=conn.execute("SELECT source_table,source_id,transaction_type,debit,credit FROM cash_ledger WHERE id=?",(ledger_id,)).fetchone()
        if not old: raise ValueError("Payment not found")
        old_party=None
        if old[0] in ("customer_payments","supplier_payments","labour_payments") and old[1] is not None:
            party_column={"customer_payments":"customer_id","supplier_payments":"supplier_id","labour_payments":"labour_id"}[old[0]]
            party_row=conn.execute(f"SELECT {party_column} FROM {old[0]} WHERE id=?",(old[1],)).fetchone();old_party=old_party if not party_row else old_party or party_row[0]
        if old[0] in ("customer_payments","supplier_payments","labour_payments") and old[1] is not None:conn.execute(f"DELETE FROM {old[0]} WHERE id=?",(old[1],))
        limits={"CUSTOMER PAYMENT":customer_outstanding(party_id,conn),"SUPPLIER PAYMENT":supplier_outstanding(party_id,conn),"LABOUR PAYMENT":labour_due(conn)}
        allowed=limits.get(payment_type)
        if allowed is not None and old[2]==payment_type and old_party==party_id:allowed=max(allowed,float(old[4] or old[3] or 0))
        if allowed is not None and amount>allowed+1e-9: raise ValueError("Payment exceeds outstanding due")
        source_table=source_id=None
        if payment_type in mapping:
            source_table,column=mapping[payment_type];source_id=conn.execute(f"INSERT INTO {source_table}(payment_date,{column},amount,payment_mode,reference_no,notes) VALUES(?,?,?,?,?,?)",(payment_date,party_id,amount,mode,reference,notes)).lastrowid
        inflow=payment_type in ("CUSTOMER PAYMENT","OTHER INCOME")
        conn.execute("UPDATE cash_ledger SET transaction_date=?,transaction_type=?,reference=?,payment_mode=?,debit=?,credit=?,notes=?,source_table=?,source_id=? WHERE id=?",(payment_date,payment_type,reference,mode,0 if inflow else amount,amount if inflow else 0,notes,source_table or "manual_payment",source_id or 0,ledger_id))
        publish("payment_changed");return ledger_id


class PaymentPage:
    def __init__(self,parent):self.parent=parent;self.frame=tk.Frame(parent,bg="#f5f6fa");self.build();self.load()
    def build(self):
        top=tk.Frame(self.frame,bg="#f5f6fa");top.pack(fill="x",padx=20,pady=15);tk.Label(top,text="💳 Payment Management",font=("Arial",22,"bold"),bg="#f5f6fa").pack(side="left");tk.Button(top,text="➕ New Payment",command=self.add).pack(side="right")
        cols=("ID","Date","Type","Reference","Mode","Debit","Credit","Notes");self.tree=ttk.Treeview(self.frame,columns=cols,show="headings")
        for c in cols:self.tree.heading(c,text=c);self.tree.column(c,width=115,anchor="center")
        self.tree.pack(fill="both",expand=True,padx=20,pady=10)
        actions=tk.Frame(self.frame,bg="#f5f6fa");actions.pack(fill="x",padx=20,pady=8)
        tk.Button(actions,text="✏ Edit",command=self.edit).pack(side="left",padx=4)
        tk.Button(actions,text="🗑 Delete",command=self.delete).pack(side="left",padx=4)
    def load(self):
        for x in self.tree.get_children():self.tree.delete(x)
        with get_connection() as c:rows=c.execute("SELECT id,transaction_date,transaction_type,reference,payment_mode,debit,credit,notes FROM cash_ledger ORDER BY id DESC").fetchall()
        for r in rows:self.tree.insert("","end",values=r)
    def add(self, ledger_id=None):
        old=None
        if ledger_id:
            with get_connection() as c: old=c.execute("SELECT transaction_date,transaction_type,reference,payment_mode,debit,credit,notes,source_table,source_id FROM cash_ledger WHERE id=?",(ledger_id,)).fetchone()
        w=tk.Toplevel(self.parent);w.title("New Payment");w.geometry("470x520");body=tk.Frame(w);body.pack(fill="x",padx=30,pady=20);widgets={};types=("CUSTOMER PAYMENT","SUPPLIER PAYMENT","LABOUR PAYMENT","OTHER PAYMENT","OTHER INCOME")
        for label in ("Date","Reference","Amount","Notes"):
            tk.Label(body,text=label).pack(anchor="w",pady=(7,2));e=tk.Entry(body);e.pack(fill="x");widgets[label]=e
        widgets["Date"].insert(0,old[0] if old else date.today().isoformat());tk.Label(body,text="Payment Type").pack(anchor="w",pady=(7,2));ptype=ttk.Combobox(body,values=types,state="readonly");ptype.set(old[1] if old else types[0]);ptype.pack(fill="x")
        tk.Label(body,text="Party").pack(anchor="w",pady=(7,2));party=ttk.Combobox(body,state="readonly");party.pack(fill="x");tk.Label(body,text="Mode").pack(anchor="w",pady=(7,2));mode=ttk.Combobox(body,values=("Cash","UPI","Bank","Other"),state="readonly");mode.set("Cash");mode.pack(fill="x");parties=[]
        def refresh(event=None):
            nonlocal parties
            with get_connection() as c:
                if ptype.get()=="CUSTOMER PAYMENT":parties=c.execute("SELECT id,name FROM customers ORDER BY name").fetchall()
                elif ptype.get()=="SUPPLIER PAYMENT":parties=c.execute("SELECT id,name FROM suppliers ORDER BY name").fetchall()
                elif ptype.get()=="LABOUR PAYMENT":parties=c.execute("SELECT id,worker_name FROM labour ORDER BY worker_name").fetchall()
                else:parties=[]
            party["values"]=[f"{i} - {n}" for i,n in parties];party.set("")
        ptype.bind("<<ComboboxSelected>>",refresh);refresh()
        if old:
            widgets["Reference"].insert(0,old[2] or "");widgets["Amount"].insert(0,old[5] if old[1]=="OTHER INCOME" else old[4]);widgets["Notes"].insert(0,old[6] or "");mode.set(old[3] or "Cash")
            for index,(party_id,party_name) in enumerate(parties):
                if party_id==old[8]:party.current(index);break
        def save():
            try:
                amount=float(widgets["Amount"].get());party_id=int(party.get().split(" - ",1)[0]) if parties else None
                args=(widgets["Date"].get().strip(),ptype.get(),party_id,amount,mode.get(),widgets["Reference"].get().strip(),widgets["Notes"].get().strip())
                if ledger_id:update_payment(ledger_id,*args)
                else:record_payment(*args)
                w.destroy();self.load()
            except (ValueError,IndexError):messagebox.showerror("Error","Party এবং positive amount দিন।",parent=w)
        tk.Button(w,text="Save Payment",command=save,bg="#27ae60",fg="white",padx=20,pady=7).pack(pady=10)
    def selected(self):
        s=self.tree.selection()
        if not s:messagebox.showwarning("Select","একটি payment select করুন।",parent=self.frame);return None
        return int(self.tree.item(s[0],"values")[0])
    def edit(self):
        i=self.selected()
        if i:self.add(i)
    def delete(self):
        i=self.selected()
        if i and messagebox.askyesno("Confirm","Payment delete করলে due ও ledger update হবে। Continue?",parent=self.frame):delete_payment(i);self.load()
    def show(self):self.frame.pack(fill="both",expand=True)


class LedgerPage(CrudPage):
    def __init__(self,parent):super().__init__(parent,"Cash / Bank Ledger","cash_ledger",(("transaction_date","Date","text",()),("transaction_type","Type","text",()),("reference","Reference","text",()),("payment_mode","Mode","choice",("Cash","UPI","Bank","Other")),("debit","Debit","number",()),("credit","Credit","number",()),("notes","Notes","text",())),"transaction_date")
    def edit(self):
        i=self.selected()
        if not i:return
        with get_connection() as c: linked=c.execute("SELECT source_table FROM cash_ledger WHERE id=?",(i,)).fetchone()
        if linked and linked[0]:messagebox.showerror("Protected","Source-linked entry source screen থেকে edit করুন।",parent=self.frame);return
        self.form(i)
    def delete(self):
        i=self.selected()
        if not i:return
        try:
            if messagebox.askyesno("Confirm","Manual ledger entry delete করবেন?",parent=self.frame):delete_manual_ledger(i);self.load()
        except PermissionError as e:messagebox.showerror("Protected",str(e),parent=self.frame)
