import sqlite3
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from database import get_connection


class CrudPage:
    def __init__(self, parent, title, table, fields, date_field=None, compute=None):
        self.parent, self.title, self.table = parent, title, table
        self.fields, self.date_field, self.compute = fields, date_field, compute
        self.frame = tk.Frame(parent, bg="#f5f6fa")
        self.build(); self.load()

    def build(self):
        top=tk.Frame(self.frame,bg="#f5f6fa"); top.pack(fill="x",padx=20,pady=15)
        tk.Label(top,text=self.title,font=("Arial",22,"bold"),bg="#f5f6fa").pack(side="left")
        tk.Button(top,text="➕ Add",command=self.add,bg="#27ae60",fg="white",padx=15,pady=7).pack(side="right")
        bar=tk.Frame(self.frame,bg="#f5f6fa"); bar.pack(fill="x",padx=20)
        tk.Label(bar,text="Search:",bg="#f5f6fa").pack(side="left")
        self.search=tk.Entry(bar,width=30); self.search.pack(side="left",padx=8); self.search.bind("<KeyRelease>",lambda e:self.load())
        tk.Button(bar,text="🔄 Refresh",command=self.load).pack(side="left")
        columns=("ID",)+tuple(label for _,label,_,_ in self.fields)
        holder=tk.Frame(self.frame); holder.pack(fill="both",expand=True,padx=20,pady=10)
        self.tree=ttk.Treeview(holder,columns=columns,show="headings")
        for col in columns: self.tree.heading(col,text=col); self.tree.column(col,width=105,anchor="center")
        scroll=ttk.Scrollbar(holder,command=self.tree.yview); self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left",fill="both",expand=True); scroll.pack(side="right",fill="y")
        actions=tk.Frame(self.frame,bg="#f5f6fa"); actions.pack(fill="x",padx=20,pady=10)
        tk.Button(actions,text="✏ Edit",command=self.edit,padx=18).pack(side="left",padx=4)
        tk.Button(actions,text="🗑 Delete",command=self.delete,padx=18).pack(side="left",padx=4)

    def load(self):
        keyword=f"%{self.search.get().strip()}%"; searchable=[name for name,_,kind,_ in self.fields if kind in ("text","choice")]
        where=" OR ".join(f"CAST({x} AS TEXT) LIKE ?" for x in searchable)
        sql=f"SELECT id,{','.join(x[0] for x in self.fields)} FROM {self.table}"+(f" WHERE {where}" if where else "")+" ORDER BY id DESC"
        with get_connection() as conn: rows=conn.execute(sql,(keyword,)*len(searchable)).fetchall()
        for item in self.tree.get_children(): self.tree.delete(item)
        for row in rows: self.tree.insert("","end",values=row)

    def selected(self):
        s=self.tree.selection()
        if not s: messagebox.showwarning("Select","একটি record select করুন।",parent=self.frame); return None
        return int(self.tree.item(s[0],"values")[0])

    def form(self, record_id=None):
        old=None
        if record_id:
            with get_connection() as conn: old=conn.execute(f"SELECT {','.join(x[0] for x in self.fields)} FROM {self.table} WHERE id=?",(record_id,)).fetchone()
        win=tk.Toplevel(self.parent); win.title(("Edit " if old else "Add ")+self.title); win.geometry("540x720")
        canvas=tk.Canvas(win); scroll=ttk.Scrollbar(win,command=canvas.yview); body=tk.Frame(canvas)
        body.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all"))); canvas.create_window((0,0),window=body,anchor="nw",width=500); canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left",fill="both",expand=True); scroll.pack(side="right",fill="y")
        widgets={}
        for i,(name,label,kind,options) in enumerate(self.fields):
            tk.Label(body,text=label).pack(anchor="w",padx=30,pady=(7,2))
            value=(old[i] if old and old[i] is not None else (date.today().isoformat() if name==self.date_field else ""))
            if kind=="choice": w=ttk.Combobox(body,values=options,state="readonly"); w.set(str(value or (options[0] if options else "")))
            else: w=tk.Entry(body); w.insert(0,str(value))
            w.pack(fill="x",padx=30); widgets[name]=w
        def save():
            try:
                values=[]; data={}
                for name,_,kind,_ in self.fields:
                    raw=widgets[name].get().strip()
                    value=float(raw or 0) if kind=="number" else raw
                    if kind=="number" and value<0: raise ValueError
                    values.append(value); data[name]=value
                if self.compute:
                    updates=self.compute(data)
                    for key,val in updates.items(): values[[f[0] for f in self.fields].index(key)]=val
                with get_connection() as conn:
                    if old: conn.execute(f"UPDATE {self.table} SET "+",".join(f"{x[0]}=?" for x in self.fields)+" WHERE id=?",tuple(values)+(record_id,))
                    else: conn.execute(f"INSERT INTO {self.table}({','.join(x[0] for x in self.fields)}) VALUES({','.join('?' for _ in values)})",values)
                win.destroy(); self.load()
            except (ValueError,ZeroDivisionError): messagebox.showerror("Error","Required fields ও non-negative numeric values পরীক্ষা করুন।",parent=win)
            except sqlite3.Error as e: messagebox.showerror("Database Error",str(e),parent=win)
        tk.Button(body,text="💾 Save",command=save,bg="#27ae60",fg="white",padx=25,pady=7).pack(pady=20)

    def add(self): self.form()
    def edit(self):
        i=self.selected()
        if i:self.form(i)
    def delete(self):
        i=self.selected()
        if i and messagebox.askyesno("Confirm","Record delete করবেন?",parent=self.frame):
            try:
                with get_connection() as conn: conn.execute(f"DELETE FROM {self.table} WHERE id=?",(i,))
                self.load()
            except sqlite3.Error as e: messagebox.showerror("Database Error",str(e),parent=self.frame)
    def show(self): self.frame.pack(fill="both",expand=True)
