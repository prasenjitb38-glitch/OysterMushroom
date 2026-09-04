import os
import shutil
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from database import DB_FILE, get_connection, hash_password, verify_password
from services import setting


class SettingsPage:
    KEYS=("business_name","address","mobile","email","gstin","logo","invoice_prefix","opening_cash","opening_bank","opening_mushroom_stock","default_payment_mode","backup_folder","units","expected_rate")
    def __init__(self,parent):self.parent=parent;self.frame=tk.Frame(parent,bg="#f5f6fa");self.build()
    def build(self):
        tk.Label(self.frame,text="⚙ Business Settings",font=("Arial",22,"bold"),bg="#f5f6fa").pack(anchor="w",padx=25,pady=15)
        form=tk.Frame(self.frame,bg="#f5f6fa");form.pack(fill="x",padx=30);self.entries={}
        with get_connection() as c:values=dict(c.execute("SELECT key,value FROM settings"))
        for key in self.KEYS:
            row=tk.Frame(form,bg="#f5f6fa");row.pack(fill="x",pady=3);tk.Label(row,text=key.replace("_"," ").title(),width=24,anchor="w",bg="#f5f6fa").pack(side="left")
            e=tk.Entry(row);e.insert(0,values.get(key,""));e.pack(side="left",fill="x",expand=True);self.entries[key]=e
            if key=="logo":tk.Button(row,text="Browse",command=lambda:self.pick("logo",[("Images","*.png *.jpg *.jpeg")])).pack(side="left")
            if key=="backup_folder":tk.Button(row,text="Browse",command=lambda:self.pick("backup_folder",None)).pack(side="left")
        tk.Button(form,text="💾 Save Settings",command=self.save,bg="#27ae60",fg="white",padx=25,pady=8).pack(pady=15)
    def pick(self,key,types):
        path=filedialog.askopenfilename(filetypes=types) if types else filedialog.askdirectory()
        if path:self.entries[key].delete(0,"end");self.entries[key].insert(0,path)
    def save(self):
        try:
            for key in ("opening_cash","opening_bank","opening_mushroom_stock","expected_rate"):
                if float(self.entries[key].get() or 0)<0:raise ValueError
            with get_connection() as c:c.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",[(k,e.get().strip()) for k,e in self.entries.items()])
            messagebox.showinfo("Saved","Settings saved.",parent=self.frame)
        except ValueError:messagebox.showerror("Error","Financial settings non-negative number হতে হবে।",parent=self.frame)
    def show(self):self.frame.pack(fill="both",expand=True)


class BackupPage:
    def __init__(self,parent):self.parent=parent;self.frame=tk.Frame(parent,bg="#f5f6fa");self.build()
    def build(self):
        tk.Label(self.frame,text="💾 Backup & Restore",font=("Arial",22,"bold"),bg="#f5f6fa").pack(pady=30)
        tk.Button(self.frame,text="One-click Backup",command=self.quick,bg="#27ae60",fg="white",padx=25,pady=10).pack(pady=8)
        tk.Button(self.frame,text="Save As Backup",command=self.save_as,padx=25,pady=10).pack(pady=8)
        tk.Button(self.frame,text="Restore Database",command=self.restore,bg="#e67e22",fg="white",padx=25,pady=10).pack(pady=8)
    def quick(self):
        folder=setting("backup_folder",os.path.dirname(DB_FILE));os.makedirs(folder,exist_ok=True);self.copy(os.path.join(folder,"mushroom_backup_"+datetime.now().strftime("%Y-%m-%d_%H%M%S")+".db"))
    def save_as(self):
        p=filedialog.asksaveasfilename(defaultextension=".db",filetypes=[("SQLite DB","*.db")]);
        if p:self.copy(p)
    def copy(self,path):
        try:
            with sqlite3.connect(DB_FILE) as src,sqlite3.connect(path) as dst:src.backup(dst)
            messagebox.showinfo("Backup",f"Backup saved:\n{path}",parent=self.frame)
        except Exception as e:messagebox.showerror("Backup Error",str(e),parent=self.frame)
    def restore(self):
        p=filedialog.askopenfilename(filetypes=[("SQLite DB","*.db")])
        if not p or not messagebox.askyesno("Confirm","Current database safety backup করে restore করবেন?",parent=self.frame):return
        try:
            safety=DB_FILE+".safety_"+datetime.now().strftime("%Y%m%d_%H%M%S");shutil.copy2(DB_FILE,safety);shutil.copy2(p,DB_FILE);messagebox.showinfo("Restored","Restore complete. Application restart করুন।",parent=self.frame)
        except Exception as e:messagebox.showerror("Restore Error",str(e),parent=self.frame)
    def show(self):self.frame.pack(fill="both",expand=True)


class UsersPage:
    def __init__(self,parent):self.parent=parent;self.frame=tk.Frame(parent,bg="#f5f6fa");self.build();self.load()
    def build(self):
        tk.Label(self.frame,text="🔐 Users & Permissions",font=("Arial",22,"bold"),bg="#f5f6fa").pack(anchor="w",padx=20,pady=15)
        self.tree=ttk.Treeview(self.frame,columns=("ID","Username","Name","Role","Active"),show="headings");
        for c in ("ID","Username","Name","Role","Active"):self.tree.heading(c,text=c)
        self.tree.pack(fill="both",expand=True,padx=20,pady=10)
        tk.Button(self.frame,text="Add User",command=self.add).pack(side="left",padx=20,pady=10);tk.Button(self.frame,text="Toggle Active",command=self.toggle).pack(side="left")
    def load(self):
        for x in self.tree.get_children():self.tree.delete(x)
        with get_connection() as c:rows=c.execute("SELECT id,username,full_name,role,active FROM users ORDER BY username").fetchall()
        for r in rows:self.tree.insert("","end",values=r)
    def add(self):
        w=tk.Toplevel(self.parent);w.title("Add User");entries={}
        for label in ("Username","Full Name","Password"):
            tk.Label(w,text=label).pack(anchor="w",padx=25,pady=(8,2));e=tk.Entry(w,show="*" if label=="Password" else "");e.pack(fill="x",padx=25);entries[label]=e
        role=ttk.Combobox(w,values=("ADMIN","MANAGER","STAFF"),state="readonly");role.set("STAFF");role.pack(fill="x",padx=25,pady=10)
        def save():
            try:
                with get_connection() as c:c.execute("INSERT INTO users(username,full_name,password_hash,role) VALUES(?,?,?,?)",(entries["Username"].get().strip(),entries["Full Name"].get().strip(),hash_password(entries["Password"].get()),role.get()))
                w.destroy();self.load()
            except sqlite3.Error as e:messagebox.showerror("Error",str(e),parent=w)
        tk.Button(w,text="Save",command=save).pack(pady=15)
    def toggle(self):
        s=self.tree.selection()
        if not s:return
        i,a=self.tree.item(s[0],"values")[0],self.tree.item(s[0],"values")[4]
        with get_connection() as c:c.execute("UPDATE users SET active=? WHERE id=?",(0 if int(a) else 1,i))
        self.load()
    def show(self):self.frame.pack(fill="both",expand=True)


def authenticate(username,password):
    with get_connection() as c:row=c.execute("SELECT id,password_hash,role,active,full_name FROM users WHERE username=?",(username,)).fetchone()
    return row if row and row[3] and verify_password(password,row[1]) else None
