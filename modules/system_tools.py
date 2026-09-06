import os
import sqlite3
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import database
from database import authenticate, get_connection, hash_password, verify_password, validate_password, set_user_active,admin_reset_password,change_password
from backup_service import (
    REQUIRED_SCHEMA,
    backup_database,
    restore_database,
    validate_backup,
)
from services import setting
from services import enforce_desktop


class SettingsPage:
    KEYS=("business_name","address","mobile","email","gstin","logo","invoice_prefix","opening_cash","opening_bank","opening_mushroom_stock","default_payment_mode","backup_folder","units","expected_rate")
    def __init__(self,parent):self.parent=parent;self.frame=tk.Frame(parent,bg="#f5f6fa");self.build()
    def build(self):
        tk.Label(self.frame,text="⚙ Business Settings",font=("Arial",22,"bold"),bg="#f5f6fa").pack(anchor="w",padx=25,pady=15)
        form=tk.Frame(self.frame,bg="#f5f6fa");form.pack(fill="x",padx=30);self.entries={}
        with get_connection() as c:
            values=dict(c.execute("SELECT key,value FROM settings"))
            self.opening_locked=bool(c.execute("SELECT 1 FROM owner_capital WHERE kind='OPENING' LIMIT 1").fetchone())
        for key in self.KEYS:
            row=tk.Frame(form,bg="#f5f6fa");row.pack(fill="x",pady=3);tk.Label(row,text=key.replace("_"," ").title(),width=24,anchor="w",bg="#f5f6fa").pack(side="left")
            e=tk.Entry(row);e.insert(0,values.get(key,""))
            if self.opening_locked and key in ("opening_cash","opening_bank"):e.configure(state="readonly")
            e.pack(side="left",fill="x",expand=True);self.entries[key]=e
            if key=="logo":tk.Button(row,text="Browse",command=lambda:self.pick("logo",[("Images","*.png *.jpg *.jpeg")])).pack(side="left")
            if key=="backup_folder":tk.Button(row,text="Browse",command=lambda:self.pick("backup_folder",None)).pack(side="left")
        tk.Button(form,text="💾 Save Settings",command=self.save,bg="#27ae60",fg="white",padx=25,pady=8).pack(pady=15)
    def pick(self,key,types):
        path=filedialog.askopenfilename(filetypes=types) if types else filedialog.askdirectory()
        if path:self.entries[key].delete(0,"end");self.entries[key].insert(0,path)
    def save(self):
        try:enforce_desktop("settings")
        except PermissionError as e:return messagebox.showerror("Forbidden",str(e),parent=self.frame)
        try:
            for key in ("opening_cash","opening_bank","opening_mushroom_stock","expected_rate"):
                if float(self.entries[key].get() or 0)<0:raise ValueError
            values=[(k,e.get().strip()) for k,e in self.entries.items()
                    if not (self.opening_locked and k in ("opening_cash","opening_bank"))]
            with get_connection() as c:c.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",values)
            messagebox.showinfo("Saved","Settings saved. Opening cash/bank remain managed by Owner's Capital." if self.opening_locked else "Settings saved.",parent=self.frame)
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
        folder=setting("backup_folder",os.path.dirname(database.DB_FILE));os.makedirs(folder,exist_ok=True);self.copy(os.path.join(folder,"mushroom_backup_"+datetime.now().strftime("%Y-%m-%d_%H%M%S")+".db"))
    def save_as(self):
        p=filedialog.asksaveasfilename(defaultextension=".db",filetypes=[("SQLite DB","*.db")]);
        if p:self.copy(p)
    def copy(self,path):
        try:
            backup_database(database.DB_FILE,path)
            messagebox.showinfo("Backup",f"Backup saved:\n{path}",parent=self.frame)
        except Exception as e:messagebox.showerror("Backup Error",str(e),parent=self.frame)
    def restore(self):
        try:enforce_desktop("backup_restore")
        except PermissionError as e:return messagebox.showerror("Forbidden",str(e),parent=self.frame)
        p=filedialog.askopenfilename(filetypes=[("SQLite DB","*.db")])
        if not p or not messagebox.askyesno("Confirm","Current database safety backup করে restore করবেন?",parent=self.frame):return
        try:
            validate_backup(p)
            safety=restore_database(p,database.DB_FILE);messagebox.showinfo("Restored",f"Restore complete.\nSafety copy: {safety}",parent=self.frame)
        except Exception as e:messagebox.showerror("Restore Error",str(e),parent=self.frame)
    def show(self):self.frame.pack(fill="both",expand=True)


class UsersPage:
    def __init__(self,parent,current_user=None):self.parent=parent;self.current_user=current_user or {"id":1,"role":"ADMIN"};self.frame=tk.Frame(parent,bg="#f5f6fa");self.build();self.load()
    def build(self):
        tk.Label(self.frame,text="🔐 Users & Permissions",font=("Arial",22,"bold"),bg="#f5f6fa").pack(anchor="w",padx=20,pady=15)
        self.tree=ttk.Treeview(self.frame,columns=("ID","Username","Name","Role","Active"),show="headings");
        for c in ("ID","Username","Name","Role","Active"):self.tree.heading(c,text=c)
        self.tree.pack(fill="both",expand=True,padx=20,pady=10)
        tk.Button(self.frame,text="Add User",command=self.add).pack(side="left",padx=20,pady=10);tk.Button(self.frame,text="Toggle Active",command=self.toggle).pack(side="left");tk.Button(self.frame,text="Reset Password",command=self.reset).pack(side="left",padx=8)
    def load(self):
        for x in self.tree.get_children():self.tree.delete(x)
        with get_connection() as c:rows=c.execute("SELECT id,username,full_name,role,active FROM users ORDER BY username").fetchall()
        for r in rows:self.tree.insert("","end",values=r)
    def add(self):
        enforce_desktop("users")
        w=tk.Toplevel(self.parent);w.title("Add User");entries={}
        for label in ("Username","Full Name","Password"):
            tk.Label(w,text=label).pack(anchor="w",padx=25,pady=(8,2));e=tk.Entry(w,show="*" if label=="Password" else "");e.pack(fill="x",padx=25);entries[label]=e
        role=ttk.Combobox(w,values=("ADMIN","MANAGER","STAFF"),state="readonly");role.set("STAFF");role.pack(fill="x",padx=25,pady=10)
        def save():
            try:
                username=entries["Username"].get().strip();password=entries["Password"].get();validate_password(password)
                if not username:raise ValueError("Username is required")
                with get_connection() as c:c.execute("INSERT INTO users(username,full_name,password_hash,role) VALUES(?,?,?,?)",(username,entries["Full Name"].get().strip(),hash_password(password),role.get()))
                w.destroy();self.load()
            except (sqlite3.Error,ValueError) as e:messagebox.showerror("Error",str(e),parent=w)
        tk.Button(w,text="Save",command=save).pack(pady=15)
    def toggle(self):
        enforce_desktop("users")
        s=self.tree.selection()
        if not s:return
        i,a=self.tree.item(s[0],"values")[0],self.tree.item(s[0],"values")[4]
        try:set_user_active(i,not int(a))
        except ValueError as e:messagebox.showerror("Protected",str(e),parent=self.frame)
        self.load()
    def reset(self):
        enforce_desktop("users")
        s=self.tree.selection()
        if not s:return
        target=int(self.tree.item(s[0],"values")[0]);w=tk.Toplevel(self.parent);w.title("Reset Password");tk.Label(w,text="Temporary password (8+ characters)").pack(padx=25,pady=8);e=tk.Entry(w,show="*");e.pack(padx=25)
        def save():
            try:admin_reset_password(self.current_user.get("id"),target,e.get());w.destroy();messagebox.showinfo("Reset","Temporary password saved. User must change it on next login.",parent=self.frame)
            except (ValueError,PermissionError) as x:messagebox.showerror("Error",str(x),parent=w)
        tk.Button(w,text="Reset",command=save).pack(pady=15)
    def show(self):self.frame.pack(fill="both",expand=True)

class ChangePasswordPage:
    def __init__(self,parent,user):self.parent=parent;self.user=user;self.frame=tk.Frame(parent,bg="#f5f6fa");self.build()
    def build(self):
        tk.Label(self.frame,text="🔑 Change Password",font=("Arial",22,"bold"),bg="#f5f6fa").pack(pady=25);entries=[]
        for label in ("Current Password","New Password","Confirm Password"):tk.Label(self.frame,text=label,bg="#f5f6fa").pack();e=tk.Entry(self.frame,show="*");e.pack();entries.append(e)
        def save():
            try:
                if entries[1].get()!=entries[2].get():raise ValueError("Passwords do not match")
                change_password(self.user["id"],entries[0].get(),entries[1].get());self.user["must_change_password"]=False;messagebox.showinfo("Success","Password changed.",parent=self.frame)
            except ValueError as e:messagebox.showerror("Error",str(e),parent=self.frame)
        tk.Button(self.frame,text="Change Password",command=save,bg="#27ae60",fg="white").pack(pady=15)
    def show(self):self.frame.pack(fill="both",expand=True)
