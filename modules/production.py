import sqlite3, tkinter as tk
from datetime import date
from tkinter import messagebox,ttk
from database import get_connection
from services import save_batch,delete_batch,save_production,delete_production,batch_summary

class ProductionPage:
 def __init__(self,parent):self.parent=parent;self.frame=tk.Frame(parent,bg="#f3f4f6");self.build();self.load_batches()
 def build(self):
  tk.Label(self.frame,text="🌱 Production Management",font=("Arial",24,"bold"),bg="#f3f4f6").pack(anchor="w",padx=25,pady=15)
  bar=tk.Frame(self.frame,bg="#f3f4f6");bar.pack(fill="x",padx=25)
  for text,cmd in (("➕ New Batch",self.batch_form),("✏ Edit Batch",self.edit_batch),("🗑 Delete Batch",self.remove_batch),("🍄 Production Entry",self.production_form),("📋 Production Records",self.production_records)):
   tk.Button(bar,text=text,command=cmd,padx=10,pady=6).pack(side="left",padx=3)
  tk.Label(bar,text="Search:",bg="#f3f4f6").pack(side="left",padx=(15,2));self.search=tk.Entry(bar,width=18);self.search.pack(side="left");self.search.bind("<KeyRelease>",lambda e:self.load_batches())
  cols=("ID","Batch","Date","Bags","Straw","Spawn","Expected","Actual","Yield %","Labour","Other Cost","Status")
  self.tree=ttk.Treeview(self.frame,columns=cols,show="headings");
  for c in cols:self.tree.heading(c,text=c);self.tree.column(c,width=90,anchor="center")
  self.tree.column("ID",width=45);self.tree.pack(fill="both",expand=True,padx=25,pady=15)
 def load_batches(self):
  for x in self.tree.get_children():self.tree.delete(x)
  with get_connection() as c:rows=c.execute("SELECT id,batch_no,production_date,status FROM batches WHERE batch_no LIKE ? ORDER BY id DESC",(f"%{self.search.get().strip()}%",)).fetchall()
  for i,b,d,status in rows:
   s=batch_summary(i);self.tree.insert("","end",values=(i,b,d,s["bags"],s["straw"],s["spawn"],s["expected_yield"],f'{s["actual_harvest"]:.2f}',f'{s["yield_pct"]:.2f}',f'{s["labour"]:.2f}',f'{s["other_cost"]:.2f}',status))
 def selected(self):
  s=self.tree.selection()
  if not s:messagebox.showwarning("Select","একটি batch select করুন।",parent=self.frame);return None
  return int(self.tree.item(s[0],"values")[0])
 def batch_form(self,batch_id=None):
  old=None
  if batch_id:
   with get_connection() as c:old=c.execute("SELECT batch_no,production_date,straw_qty,spawn_qty,bag_count,expected_yield,expected_harvest_date,status,notes FROM batches WHERE id=?",(batch_id,)).fetchone()
  w=tk.Toplevel(self.parent);w.title("Edit Batch" if old else "New Batch");w.geometry("480x650");body=tk.Frame(w);body.pack(fill="x",padx=30,pady=15);entries={}
  fields=("batch_no","production_date","straw_qty","spawn_qty","bag_count","expected_yield","expected_harvest_date","notes")
  for n in fields:tk.Label(body,text=n.replace("_"," ").title()).pack(anchor="w");e=tk.Entry(body);e.insert(0,str(old[fields.index(n)] or "") if old else (date.today().isoformat() if n=="production_date" else ""));e.pack(fill="x",pady=(0,6));entries[n]=e
  tk.Label(body,text="Status").pack(anchor="w");status=ttk.Combobox(body,values=("Preparing","Incubation","Fruiting","Harvesting","Completed","Failed"),state="readonly");status.set(old[7] if old else "Preparing");status.pack(fill="x")
  def save():
   try:save_batch({**{n:entries[n].get().strip() for n in fields},"status":status.get()},batch_id);w.destroy();self.load_batches()
   except (ValueError,sqlite3.Error) as e:messagebox.showerror("Error",str(e),parent=w)
  tk.Button(body,text="💾 Save",command=save,bg="#27ae60",fg="white",pady=7).pack(pady=15)
 def edit_batch(self):
  i=self.selected()
  if i:self.batch_form(i)
 def remove_batch(self):
  i=self.selected()
  if i and messagebox.askyesno("Confirm","Dependent records না থাকলে batch delete হবে।",parent=self.frame):
   try:delete_batch(i);self.load_batches()
   except ValueError as e:messagebox.showerror("Cannot Delete",str(e),parent=self.frame)
 def production_form(self,record_id=None,refresh=None):
  old=None
  with get_connection() as c:
   batches=c.execute("SELECT id,batch_no FROM batches ORDER BY batch_no").fetchall()
   if record_id:old=c.execute("SELECT production_date,batch_id,bags,production_kg,wastage_kg,notes FROM daily_production WHERE id=?",(record_id,)).fetchone()
  w=tk.Toplevel(self.parent);w.title("Daily Production");w.geometry("440x480");body=tk.Frame(w);body.pack(fill="x",padx=30,pady=15)
  tk.Label(body,text="Date").pack(anchor="w");dt=tk.Entry(body);dt.insert(0,old[0] if old else date.today().isoformat());dt.pack(fill="x")
  tk.Label(body,text="Batch").pack(anchor="w");batch=ttk.Combobox(body,values=[b[1] for b in batches],state="readonly");batch.pack(fill="x");batch.current(([b[0] for b in batches].index(old[1]) if old and old[1] in [b[0] for b in batches] else 0) if batches else -1)
  es=[]
  for label,val in (("Bags",old[2] if old else ""),("Production Kg",old[3] if old else ""),("Wastage Kg",old[4] if old else ""),("Notes",old[5] if old else "")):
   tk.Label(body,text=label).pack(anchor="w");e=tk.Entry(body);e.insert(0,str(val or ""));e.pack(fill="x");es.append(e)
  def save():
   try:save_production({"production_date":dt.get(),"batch_id":batches[batch.current()][0],"bags":es[0].get(),"production_kg":es[1].get(),"wastage_kg":es[2].get(),"notes":es[3].get()},record_id);w.destroy();(refresh or self.load_batches)()
   except (ValueError,IndexError) as e:messagebox.showerror("Error",str(e),parent=w)
  tk.Button(body,text="💾 Save",command=save,bg="#27ae60",fg="white").pack(pady=18)
 def production_records(self):
  w=tk.Toplevel(self.parent);w.title("Production Records");w.geometry("950x550");top=tk.Frame(w);top.pack(fill="x",padx=15,pady=10);search=tk.Entry(top);search.pack(side="left");cols=("ID","Date","Batch","Bags","Production","Wastage","Saleable","Per Bag","Wastage %")
  tree=ttk.Treeview(w,columns=cols,show="headings");[tree.heading(c,text=c) for c in cols];tree.pack(fill="both",expand=True,padx=15,pady=5)
  total=tk.Label(w,font=("Arial",11,"bold"));total.pack()
  def load(*_):
   for x in tree.get_children():tree.delete(x)
   with get_connection() as c:rows=c.execute("SELECT id,production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg FROM daily_production WHERE batch_no LIKE ? OR production_date LIKE ? ORDER BY production_date DESC,id DESC",(f"%{search.get()}%",f"%{search.get()}%")).fetchall()
   for r in rows:tree.insert("","end",values=r+(f"{r[4]/r[3]:.2f}" if r[3] else "0.00",f"{r[5]/r[4]*100:.2f}" if r[4] else "0.00"))
   total.config(text=f"Records: {len(rows)}   Total: {sum(r[4] for r in rows):.2f} Kg   Average: {(sum(r[4] for r in rows)/len(rows) if rows else 0):.2f} Kg")
  search.bind("<KeyRelease>",load);load()
  def rid():
   s=tree.selection();return int(tree.item(s[0],"values")[0]) if s else None
  tk.Button(top,text="Edit",command=lambda:self.production_form(rid(),load) if rid() else None).pack(side="left",padx=5)
  def remove():
   i=rid()
   if i and messagebox.askyesno("Confirm","Production record delete করবেন?",parent=w):delete_production(i);load()
  tk.Button(top,text="Delete",command=remove).pack(side="left")
 def show(self):self.frame.pack(fill="both",expand=True)
 def hide(self):self.frame.pack_forget()
