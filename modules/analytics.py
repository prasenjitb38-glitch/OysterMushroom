import csv
import tkinter as tk
from datetime import date, timedelta
from tkinter import filedialog, messagebox, ttk

from database import get_connection
from services import batch_cost_rows, pnl


class BatchCostPage:
    def __init__(self,parent):
        self.frame=tk.Frame(parent,bg="#f5f6fa"); self.build()
    def build(self):
        tk.Label(self.frame,text="💰 Batch Cost",font=("Arial",22,"bold"),bg="#f5f6fa").pack(anchor="w",padx=20,pady=15)
        cols=("Batch","Date","Bags","Production","Wastage","Saleable","Total Cost","Cost/Bag","Cost/Kg","Expected Sales","Expected Profit")
        self.tree=ttk.Treeview(self.frame,columns=cols,show="headings")
        for c in cols:self.tree.heading(c,text=c);self.tree.column(c,width=105,anchor="center")
        self.tree.pack(fill="both",expand=True,padx=20,pady=10);self.load()
    def load(self):
        for x in self.tree.get_children():self.tree.delete(x)
        for row in batch_cost_rows():self.tree.insert("","end",values=(row[0],row[1],row[2])+tuple(f"{x:.2f}" for x in row[3:]))
    def show(self):self.frame.pack(fill="both",expand=True)


class PnLPage:
    def __init__(self,parent):
        self.frame=tk.Frame(parent,bg="#f5f6fa"); self.build();self.load()
    def build(self):
        top=tk.Frame(self.frame,bg="#f5f6fa");top.pack(fill="x",padx=20,pady=15)
        tk.Label(top,text="📈 Profit & Loss",font=("Arial",22,"bold"),bg="#f5f6fa").pack(side="left")
        self.period=ttk.Combobox(top,values=("All","Today","This Week","This Month","Custom"),state="readonly",width=14);self.period.set("All");self.period.pack(side="left",padx=12)
        self.start=tk.Entry(top,width=12);self.end=tk.Entry(top,width=12);self.start.pack(side="left");self.end.pack(side="left",padx=5)
        tk.Button(top,text="Refresh",command=self.load).pack(side="left")
        self.cards=tk.Frame(self.frame,bg="#f5f6fa");self.cards.pack(fill="x",padx=20)
    def load(self):
        today=date.today(); mode=self.period.get(); start=end=None
        if mode=="Today":start=end=today.isoformat()
        elif mode=="This Week":start=(today-timedelta(days=today.weekday())).isoformat();end=today.isoformat()
        elif mode=="This Month":start=today.replace(day=1).isoformat();end=today.isoformat()
        elif mode=="Custom":start=self.start.get().strip();end=self.end.get().strip()
        values=pnl(start,end)
        for w in self.cards.winfo_children():w.destroy()
        for i,(label,key,suffix) in enumerate((("Sales","sales","₹"),("COGS","cogs","₹"),("Gross Profit","gross","₹"),("Operating Expense","expenses","₹"),("Net Profit","net","₹"),("Margin","margin","%"),("Profit/Kg","per_kg","₹"))):
            box=tk.Frame(self.cards,bg="white",bd=1,relief="solid");box.grid(row=i//4,column=i%4,sticky="nsew",padx=5,pady=5);self.cards.columnconfigure(i%4,weight=1)
            tk.Label(box,text=label,bg="white").pack(pady=(10,2));tk.Label(box,text=f"{suffix}{values[key]:,.2f}" if suffix=="₹" else f"{values[key]:.2f}{suffix}",font=("Arial",16,"bold"),bg="white").pack(pady=(0,10))
    def show(self):self.frame.pack(fill="both",expand=True)


REPORTS={
    "Production":("production_date","SELECT production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg FROM daily_production","Date,Batch,Bags,Production,Wastage,Saleable"),
    "Harvest":("harvest_date","SELECT harvest_date,batch_no,flush_no,quantity_kg,wastage_kg,grade FROM harvests","Date,Batch,Flush,Harvest,Wastage,Grade"),
    "Sales":("sale_date","SELECT sale_date,invoice_no,quantity_kg,total_amount,paid_amount,total_amount-paid_amount FROM sales","Date,Invoice,Qty,Total,Paid,Due"),
    "Expenses":("expense_date","SELECT expense_date,category,description,amount,payment_mode,batch_no FROM expenses","Date,Category,Description,Amount,Mode,Batch"),
    "Purchases":("purchase_date","SELECT purchase_date,purchase_invoice,item,quantity,total_amount,due_amount FROM purchases","Date,Invoice,Item,Qty,Total,Due"),
    "Labour":("work_date","SELECT work_date,worker_name,work_type,batch_no,amount,amount-paid FROM labour","Date,Worker,Work,Batch,Amount,Due"),
    "Payments":("transaction_date","SELECT transaction_date,transaction_type,reference,payment_mode,debit,credit FROM cash_ledger","Date,Type,Reference,Mode,Debit,Credit"),
}


class ReportsPage:
    def __init__(self,parent):
        self.frame=tk.Frame(parent,bg="#f5f6fa");self.rows=[];self.build();self.load()
    def build(self):
        top=tk.Frame(self.frame,bg="#f5f6fa");top.pack(fill="x",padx=20,pady=15)
        tk.Label(top,text="📊 Reports",font=("Arial",22,"bold"),bg="#f5f6fa").pack(side="left")
        self.kind=ttk.Combobox(top,values=tuple(REPORTS),state="readonly");self.kind.set("Production");self.kind.pack(side="left",padx=10)
        self.start=tk.Entry(top,width=12);self.end=tk.Entry(top,width=12);self.start.pack(side="left");self.end.pack(side="left",padx=4)
        self.search=tk.Entry(top,width=18);self.search.pack(side="left",padx=4)
        tk.Button(top,text="Refresh",command=self.load).pack(side="left");tk.Button(top,text="Export CSV",command=self.export).pack(side="left",padx=4)
        self.holder=tk.Frame(self.frame);self.holder.pack(fill="both",expand=True,padx=20,pady=10)
    def load(self):
        for w in self.holder.winfo_children():w.destroy()
        date_col,sql,head=REPORTS[self.kind.get()];params=[];clauses=[]
        if self.start.get().strip() and self.end.get().strip():clauses.append(f"{date_col} BETWEEN ? AND ?");params += [self.start.get().strip(),self.end.get().strip()]
        if self.search.get().strip():clauses.append("CAST("+date_col+" AS TEXT) LIKE ?");params.append(f"%{self.search.get().strip()}%")
        if clauses:sql+=" WHERE "+" AND ".join(clauses)
        with get_connection() as conn:self.rows=conn.execute(sql+f" ORDER BY {date_col} DESC",params).fetchall()
        cols=tuple(head.split(","));self.tree=ttk.Treeview(self.holder,columns=cols,show="headings")
        for c in cols:self.tree.heading(c,text=c);self.tree.column(c,width=130,anchor="center")
        for row in self.rows:self.tree.insert("","end",values=row)
        self.tree.pack(fill="both",expand=True)
    def export(self):
        path=filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if path:
            with open(path,"w",newline="",encoding="utf-8-sig") as f:w=csv.writer(f);w.writerow(REPORTS[self.kind.get()][2].split(","));w.writerows(self.rows)
    def show(self):self.frame.pack(fill="both",expand=True)


class ChartsPage:
    def __init__(self,parent):
        self.frame=tk.Frame(parent,bg="#f5f6fa");self.build()
    def build(self):
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except ImportError:
            tk.Label(self.frame,text="Charts-এর জন্য install করুন: pip install matplotlib",font=("Arial",15),bg="#f5f6fa").pack(pady=60);return
        with get_connection() as conn:rows=conn.execute("SELECT production_date,SUM(production_kg),SUM(wastage_kg) FROM daily_production GROUP BY production_date ORDER BY production_date").fetchall()
        fig=Figure(figsize=(9,5));ax=fig.add_subplot(111);ax.plot([r[0] for r in rows],[r[1] for r in rows],marker="o",label="Production");ax.plot([r[0] for r in rows],[r[2] for r in rows],label="Wastage");ax.legend();ax.set_title("Production & Wastage Trend");FigureCanvasTkAgg(fig,master=self.frame).get_tk_widget().pack(fill="both",expand=True,padx=20,pady=20)
    def show(self):self.frame.pack(fill="both",expand=True)
