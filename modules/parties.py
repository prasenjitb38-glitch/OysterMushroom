import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from database import get_connection
from services import customer_statement,supplier_statement


class PartyPage:
    def __init__(self, parent, kind):
        self.parent, self.kind = parent, kind
        self.table = "customers" if kind == "Customer" else "suppliers"
        self.frame = tk.Frame(parent, bg="#f5f6fa")
        self.build()
        self.load()

    def build(self):
        top = tk.Frame(self.frame, bg="#f5f6fa")
        top.pack(fill="x", padx=20, pady=15)
        tk.Label(top, text=f"👥 {self.kind} Management", font=("Arial", 22, "bold"), bg="#f5f6fa").pack(side="left")
        tk.Button(top, text=f"➕ Add {self.kind}", command=self.add, bg="#27ae60", fg="white", padx=15, pady=7).pack(side="right")
        search = tk.Frame(self.frame, bg="#f5f6fa")
        search.pack(fill="x", padx=20, pady=5)
        tk.Label(search, text="Search:", bg="#f5f6fa").pack(side="left")
        self.search = tk.Entry(search, width=30)
        self.search.pack(side="left", padx=8)
        self.search.bind("<KeyRelease>", lambda event: self.load())
        tk.Button(search, text="🔄 Refresh", command=self.load).pack(side="left")
        columns = ("ID", "Name", "Mobile", "Email", "Address", "Opening Due", "Purchase", "Paid", "Outstanding", "Last Purchase")
        holder = tk.Frame(self.frame)
        holder.pack(fill="both", expand=True, padx=20, pady=10)
        self.tree = ttk.Treeview(holder, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=105, anchor="center")
        self.tree.column("Address", width=160)
        bar = ttk.Scrollbar(holder, command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda event: self.history())
        actions = tk.Frame(self.frame, bg="#f5f6fa")
        actions.pack(fill="x", padx=20, pady=10)
        tk.Button(actions, text="✏ Edit", command=self.edit, padx=15).pack(side="left", padx=4)
        tk.Button(actions, text="🗑 Delete", command=self.delete, padx=15).pack(side="left", padx=4)
        tk.Button(actions, text="📋 History", command=self.history, padx=15).pack(side="left", padx=4)

    def rows(self):
        pattern = f"%{self.search.get().strip()}%"
        with get_connection() as conn:
            if self.kind == "Customer":
                return conn.execute("""
                    SELECT c.id,c.name,COALESCE(c.mobile,''),COALESCE(c.email,''),COALESCE(c.address,''),
                           COALESCE(c.opening_due,0),COALESCE(SUM(s.total_amount),0),
                           COALESCE(SUM(s.paid_amount),0)+COALESCE((SELECT SUM(amount) FROM customer_payments p WHERE p.customer_id=c.id),0),
                           COALESCE(c.opening_due,0)+COALESCE(SUM(s.total_amount-s.paid_amount),0)-COALESCE((SELECT SUM(amount) FROM customer_payments p WHERE p.customer_id=c.id),0),
                           COALESCE(MAX(s.sale_date),'')
                    FROM customers c LEFT JOIN sales s ON s.customer_id=c.id
                    WHERE c.name LIKE ? OR COALESCE(c.mobile,'') LIKE ?
                    GROUP BY c.id ORDER BY c.name
                """, (pattern, pattern)).fetchall()
            return conn.execute("""
                SELECT s.id,s.name,COALESCE(s.mobile,''),COALESCE(s.email,''),COALESCE(s.address,''),
                       COALESCE(s.opening_due,0),COALESCE(SUM(p.total_amount),0),
                       COALESCE(SUM(p.paid_amount),0)+COALESCE((SELECT SUM(amount) FROM supplier_payments x WHERE x.supplier_id=s.id),0),
                       COALESCE(s.opening_due,0)+COALESCE(SUM(p.total_amount-p.paid_amount),0)-COALESCE((SELECT SUM(amount) FROM supplier_payments x WHERE x.supplier_id=s.id),0),
                       COALESCE(MAX(p.purchase_date),'')
                FROM suppliers s LEFT JOIN purchases p ON p.supplier_id=s.id
                WHERE s.name LIKE ? OR COALESCE(s.mobile,'') LIKE ?
                GROUP BY s.id ORDER BY s.name
            """, (pattern, pattern)).fetchall()

    def load(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        for row in self.rows():
            self.tree.insert("", "end", values=row[:6] + tuple(f"₹{x:,.2f}" for x in row[6:9]) + (row[9],))

    def selected_id(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Select", f"একটি {self.kind.lower()} select করুন।", parent=self.frame)
            return None
        return int(self.tree.item(selected[0], "values")[0])

    def form(self, record_id=None):
        old = None
        if record_id:
            with get_connection() as conn:
                old = conn.execute(f"SELECT name,mobile,address,email,notes,opening_due FROM {self.table} WHERE id=?", (record_id,)).fetchone()
        window = tk.Toplevel(self.parent)
        window.title(("Edit " if old else "Add ") + self.kind)
        window.geometry("480x520")
        form = tk.Frame(window); form.pack(fill="x", padx=35, pady=20)
        fields = {}
        for i, label in enumerate(("Name", "Mobile", "Address", "Email", "Notes", "Opening Due")):
            tk.Label(form, text=label).pack(anchor="w", pady=(7,2))
            entry = tk.Entry(form); entry.pack(fill="x")
            entry.insert(0, "" if not old or old[i] is None else str(old[i])); fields[label]=entry
        def save():
            try:
                name=fields["Name"].get().strip(); due=float(fields["Opening Due"].get() or 0)
                if not name or due < 0: raise ValueError
                values=(name,fields["Mobile"].get().strip(),fields["Address"].get().strip(),fields["Email"].get().strip(),fields["Notes"].get().strip(),due)
                with get_connection() as conn:
                    if old: conn.execute(f"UPDATE {self.table} SET name=?,mobile=?,address=?,email=?,notes=?,opening_due=? WHERE id=?", values+(record_id,))
                    else: conn.execute(f"INSERT INTO {self.table}(name,mobile,address,email,notes,opening_due) VALUES(?,?,?,?,?,?)", values)
                window.destroy(); self.load()
            except ValueError: messagebox.showerror("Error", "Name এবং non-negative Opening Due দিন।", parent=window)
            except sqlite3.Error as error: messagebox.showerror("Database Error", str(error), parent=window)
        tk.Button(window,text="💾 Save",command=save,bg="#27ae60",fg="white",padx=25,pady=7).pack(pady=15)

    def add(self): self.form()
    def edit(self):
        record_id=self.selected_id()
        if record_id: self.form(record_id)
    def delete(self):
        record_id=self.selected_id()
        if not record_id or not messagebox.askyesno("Confirm", f"এই {self.kind.lower()} delete করবেন?", parent=self.frame): return
        try:
            with get_connection() as conn: conn.execute(f"DELETE FROM {self.table} WHERE id=?",(record_id,))
            self.load()
        except sqlite3.IntegrityError: messagebox.showerror("Cannot Delete", "Related transaction থাকায় delete করা যাবে না।", parent=self.frame)

    def history(self):
        record_id=self.selected_id()
        if not record_id: return
        window=tk.Toplevel(self.parent); window.title(f"{self.kind} Statement"); window.geometry("850x500");bar=tk.Frame(window);bar.pack(fill="x",padx=15,pady=8);tk.Label(bar,text="From").pack(side="left");start=tk.Entry(bar,width=12);start.pack(side="left");tk.Label(bar,text="To").pack(side="left");end=tk.Entry(bar,width=12);end.pack(side="left")
        columns=("Date","Reference","Debit","Credit","Balance");tree=ttk.Treeview(window,columns=columns,show="headings")
        for col in columns: tree.heading(col,text=col); tree.column(col,width=115,anchor="center")
        tree.pack(fill="both",expand=True,padx=15,pady=8);opening_label=tk.Label(window,font=("Arial",11,"bold"));opening_label.pack()
        def load():
            for x in tree.get_children():tree.delete(x)
            opening,rows=(customer_statement if self.kind=="Customer" else supplier_statement)(record_id,start.get().strip() or None,end.get().strip() or None);opening_label.config(text=f"Opening Balance: ₹{opening:,.2f}")
            for row in rows:tree.insert("","end",values=(row[0],row[1],f"₹{row[2]:,.2f}",f"₹{row[3]:,.2f}",f"₹{row[4]:,.2f}"))
        tk.Button(bar,text="Filter",command=load).pack(side="left",padx=6);load()

    def show(self): self.frame.pack(fill="both", expand=True)


class CustomerPage(PartyPage):
    def __init__(self, parent): super().__init__(parent, "Customer")


class SupplierPage(PartyPage):
    def __init__(self, parent): super().__init__(parent, "Supplier")
