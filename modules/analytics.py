import csv
import tkinter as tk
from datetime import date, timedelta
from tkinter import filedialog, messagebox, ttk

from database import get_connection
from services import batch_cost_rows, pnl

def chart_datasets():
    with get_connection() as conn:return {
      "Production":conn.execute("SELECT production_date,SUM(production_kg) FROM daily_production GROUP BY production_date").fetchall(),
      "Wastage":conn.execute("SELECT harvest_date,SUM(wastage_kg) FROM harvests GROUP BY harvest_date").fetchall(),
      "Harvest":conn.execute("SELECT harvest_date,SUM(quantity_kg-wastage_kg) FROM harvests GROUP BY harvest_date").fetchall(),
      "Sales":conn.execute("SELECT sale_date,SUM(total_amount) FROM sales GROUP BY sale_date").fetchall(),
      "Expense":conn.execute("SELECT expense_date,SUM(amount) FROM expenses GROUP BY expense_date").fetchall(),
      "Profit":conn.execute("SELECT d, SUM(v) FROM (SELECT sale_date d,total_amount v FROM sales UNION ALL SELECT expense_date d,-amount v FROM expenses) GROUP BY d").fetchall(),
      "Monthly Production":conn.execute("SELECT substr(production_date,1,7),SUM(production_kg) FROM daily_production GROUP BY substr(production_date,1,7)").fetchall(),
      "Monthly Sales":conn.execute("SELECT substr(sale_date,1,7),SUM(total_amount) FROM sales GROUP BY substr(sale_date,1,7)").fetchall(),
      "Batch Profit":conn.execute("SELECT b.batch_no,COALESCE((SELECT SUM(s.total_amount) FROM sales s WHERE s.batch_id=b.id),0)-COALESCE((SELECT SUM(e.amount) FROM expenses e WHERE e.batch_no=b.batch_no),0)-COALESCE((SELECT SUM(l.amount) FROM labour l WHERE l.batch_no=b.batch_no),0) FROM batches b").fetchall()}

def generate_chart_file(path):
    from matplotlib.figure import Figure
    fig=Figure(figsize=(9,6));ax=fig.add_subplot(111)
    for name,rows in chart_datasets().items():ax.plot([r[0] for r in rows],[r[1] for r in rows],marker="o",label=name)
    ax.legend();ax.set_title("Live Business Trends");fig.savefig(path);return path


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
    "Customer Due":(None,"SELECT c.name,c.opening_due+COALESCE(SUM(s.total_amount-s.paid_amount),0)-COALESCE((SELECT SUM(amount) FROM customer_payments p WHERE p.customer_id=c.id),0) FROM customers c LEFT JOIN sales s ON s.customer_id=c.id GROUP BY c.id","Customer,Due"),
    "Supplier Due":(None,"SELECT s.name,s.opening_due+COALESCE(SUM(p.total_amount-p.paid_amount),0)-COALESCE((SELECT SUM(amount) FROM supplier_payments x WHERE x.supplier_id=s.id),0) FROM suppliers s LEFT JOIN purchases p ON p.supplier_id=s.id GROUP BY s.id","Supplier,Due"),
    "Labour Due":("work_date","SELECT work_date,worker_name,amount,paid,amount-paid FROM labour","Date,Worker,Amount,Paid,Due"),
    "Cash Ledger":("transaction_date","SELECT transaction_date,transaction_type,reference,debit,credit FROM cash_ledger WHERE payment_mode='Cash'","Date,Type,Reference,Debit,Credit"),
    "Bank Ledger":("transaction_date","SELECT transaction_date,transaction_type,reference,debit,credit FROM cash_ledger WHERE payment_mode IN ('Bank','UPI')","Date,Type,Reference,Debit,Credit"),
    "Batch Cost":(None,"SELECT b.batch_no,COALESCE((SELECT SUM(total_amount) FROM purchases p WHERE p.batch_no=b.batch_no),0)+COALESCE((SELECT SUM(amount) FROM expenses e WHERE e.batch_no=b.batch_no),0)+COALESCE((SELECT SUM(amount) FROM labour l WHERE l.batch_no=b.batch_no),0) FROM batches b","Batch,Total Cost"),
    "Raw Material Stock":(None,"SELECT item,unit,opening_stock,reorder_level FROM raw_materials","Material,Unit,Opening,Minimum"),
    "Stock Movements":("entry_date","SELECT transaction_date AS entry_date,transaction_type,batch_no,quantity_kg,notes FROM stock_transactions","Date,Type,Batch,Quantity,Notes"),
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
        tk.Button(top,text="Refresh",command=self.load).pack(side="left");tk.Button(top,text="Clear",command=self.clear).pack(side="left",padx=3);tk.Button(top,text="Export CSV",command=self.export).pack(side="left",padx=4);tk.Button(top,text="Print View",command=self.print_view).pack(side="left")
        self.holder=tk.Frame(self.frame);self.holder.pack(fill="both",expand=True,padx=20,pady=10)
        self.total=tk.Label(self.frame,bg="#f5f6fa",font=("Arial",10,"bold"));self.total.pack(anchor="e",padx=25,pady=4)
    def load(self):
        for w in self.holder.winfo_children():w.destroy()
        date_col,sql,head=REPORTS[self.kind.get()];params=[];clauses=[]
        has_where=" WHERE " in sql.upper()
        if date_col and self.start.get().strip() and self.end.get().strip():clauses.append(f"{date_col} BETWEEN ? AND ?");params += [self.start.get().strip(),self.end.get().strip()]
        if clauses:sql+=(" AND " if has_where else " WHERE ")+" AND ".join(clauses)
        with get_connection() as conn:self.rows=conn.execute(sql+(f" ORDER BY {date_col} DESC" if date_col else ""),params).fetchall()
        key=self.search.get().strip().lower()
        if key:self.rows=[r for r in self.rows if key in " ".join(str(x) for x in r).lower()]
        cols=tuple(head.split(","));self.tree=ttk.Treeview(self.holder,columns=cols,show="headings")
        for c in cols:self.tree.heading(c,text=c);self.tree.column(c,width=130,anchor="center")
        for row in self.rows:self.tree.insert("","end",values=row)
        self.tree.pack(fill="both",expand=True)
        sums=[]
        for i in range(len(cols)):
            nums=[float(r[i]) for r in self.rows if isinstance(r[i],(int,float))]
            if nums:sums.append(f"{cols[i]}: {sum(nums):,.2f}")
        self.total.config(text="   ".join(sums))
    def clear(self):self.start.delete(0,"end");self.end.delete(0,"end");self.search.delete(0,"end");self.load()
    def print_view(self):
        w=tk.Toplevel(self.frame);w.title(self.kind.get()+" Report");text=tk.Text(w,width=120,height=35);text.pack(fill="both",expand=True);text.insert("end",REPORTS[self.kind.get()][2].replace(",","\t")+"\n");[text.insert("end","\t".join(str(x) for x in r)+"\n") for r in self.rows];text.insert("end","\n"+self.total.cget("text"));text.config(state="disabled")
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
        datasets=chart_datasets()
        fig=Figure(figsize=(9,6));ax=fig.add_subplot(111)
        for name,rows in datasets.items():ax.plot([r[0] for r in rows],[r[1] for r in rows],marker="o",label=name)
        ax.legend();ax.set_title("Live Business Trends");ax.tick_params(axis='x',rotation=30);FigureCanvasTkAgg(fig,master=self.frame).get_tk_widget().pack(fill="both",expand=True,padx=20,pady=20)
    def show(self):self.frame.pack(fill="both",expand=True)
