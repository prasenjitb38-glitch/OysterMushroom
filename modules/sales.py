import sqlite3
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from database import get_connection
from services import mushroom_stock


class SalesPage:
    @staticmethod
    def validate_sale(qty, rate, discount, paid, available):
        total = qty * rate - discount
        if qty <= 0 or rate <= 0 or discount < 0 or total < 0 or paid < 0 or paid > total:
            raise ValueError("Invalid sale values")
        if qty > available:
            raise OverflowError(f"Available stock: {available:.2f} Kg")
        return total

    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent, bg="#f5f6fa")
        self.create_ui()
        self.load_sales()

    def create_ui(self):
        title = tk.Frame(self.frame, bg="#f5f6fa")
        title.pack(fill="x", padx=20, pady=15)
        tk.Label(title, text="🛒 Sales Management", font=("Arial", 22, "bold"), bg="#f5f6fa").pack(side="left")
        tk.Button(title, text="➕ New Sale", command=self.new_sale, bg="#27ae60", fg="white", font=("Arial", 10, "bold"), padx=15, pady=7).pack(side="right", padx=5)
        tk.Button(title, text="🔄 Refresh", command=self.load_sales, bg="#3498db", fg="white", font=("Arial", 10, "bold"), padx=15, pady=7).pack(side="right", padx=5)

        cards = tk.Frame(self.frame, bg="#f5f6fa")
        cards.pack(fill="x", padx=20)
        self.qty_label = self.create_card(cards, "🍄 Total Sold", "0 Kg")
        self.sales_label = self.create_card(cards, "💰 Total Sales", "₹0")
        self.paid_label = self.create_card(cards, "✅ Total Paid", "₹0")
        self.due_label = self.create_card(cards, "⚠️ Total Due", "₹0")

        search = tk.Frame(self.frame, bg="#f5f6fa")
        search.pack(fill="x", padx=20, pady=15)
        tk.Label(search, text="Search Invoice / Customer:", bg="#f5f6fa").pack(side="left")
        self.search_entry = tk.Entry(search, width=30)
        self.search_entry.pack(side="left", padx=10)
        tk.Button(search, text="🔍 Search", command=self.search_sales, bg="#34495e", fg="white").pack(side="left")
        tk.Button(search, text="Clear", command=self.load_sales).pack(side="left", padx=5)

        table_frame = tk.Frame(self.frame, bg="white")
        table_frame.pack(fill="both", expand=True, padx=20, pady=10)
        columns = ("ID", "Invoice", "Date", "Customer", "Qty Kg", "Rate/Kg", "Discount", "Total", "Paid", "Due", "Payment")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        widths = (45, 95, 90, 140, 75, 85, 80, 95, 95, 95, 90)
        for column, width in zip(columns, widths):
            self.tree.heading(column, text=column)
            self.tree.column(column, width=width, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        bottom = tk.Frame(self.frame, bg="#f5f6fa")
        bottom.pack(fill="x", padx=20, pady=10)
        tk.Button(bottom, text="✏️ Edit Selected", command=self.edit_sale, bg="#f39c12", fg="white", font=("Arial", 10, "bold"), padx=15, pady=6).pack(side="left", padx=5)
        tk.Button(bottom, text="🗑️ Delete Selected", command=self.delete_sale, bg="#e74c3c", fg="white", font=("Arial", 10, "bold"), padx=15, pady=6).pack(side="left", padx=5)
        tk.Button(bottom, text="🧾 View Invoice", command=self.view_invoice, bg="#8e44ad", fg="white", font=("Arial", 10, "bold"), padx=15, pady=6).pack(side="left", padx=5)
        tk.Button(bottom, text="📄 Save PDF", command=self.save_invoice_pdf, bg="#34495e", fg="white", font=("Arial", 10, "bold"), padx=15, pady=6).pack(side="left", padx=5)

    @staticmethod
    def create_card(parent, title, value):
        frame = tk.Frame(parent, bg="white", bd=1, relief="solid", height=90)
        frame.pack(side="left", fill="both", expand=True, padx=5)
        frame.pack_propagate(False)
        tk.Label(frame, text=title, font=("Arial", 10), bg="white").pack(pady=(12, 3))
        label = tk.Label(frame, text=value, font=("Arial", 17, "bold"), bg="white")
        label.pack()
        return label

    @staticmethod
    def _select_sales(where="", parameters=()):
        sql = """
            SELECT s.id, s.invoice_no, s.sale_date,
                   COALESCE(c.name, 'Cash Customer'), s.quantity_kg,
                   s.rate_per_kg, s.discount, s.total_amount, s.paid_amount,
                   s.total_amount-s.paid_amount, COALESCE(s.payment_mode, '')
            FROM sales s LEFT JOIN customers c ON s.customer_id=c.id
        """ + where + " ORDER BY s.id DESC"
        with get_connection() as conn:
            return conn.execute(sql, parameters).fetchall()

    def _display_rows(self, rows):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            self.tree.insert("", "end", values=(
                row[0], row[1], row[2], row[3], f"{row[4]:.2f}",
                f"₹{row[5]:.2f}", f"₹{row[6]:.2f}", f"₹{row[7]:.2f}",
                f"₹{row[8]:.2f}", f"₹{row[9]:.2f}", row[10]
            ))

    def load_sales(self):
        self.search_entry.delete(0, tk.END)
        rows = self._select_sales()
        self._display_rows(rows)
        total_qty = sum(row[4] or 0 for row in rows)
        total_sales = sum(row[7] or 0 for row in rows)
        total_paid = sum(row[8] or 0 for row in rows)
        self.qty_label.config(text=f"{total_qty:.2f} Kg")
        self.sales_label.config(text=f"₹{total_sales:,.2f}")
        self.paid_label.config(text=f"₹{total_paid:,.2f}")
        self.due_label.config(text=f"₹{total_sales-total_paid:,.2f}")

    def search_sales(self):
        keyword = self.search_entry.get().strip()
        if not keyword:
            self.load_sales()
            return
        pattern = f"%{keyword}%"
        self._display_rows(self._select_sales(
            " WHERE s.invoice_no LIKE ? OR c.name LIKE ?", (pattern, pattern)
        ))

    @staticmethod
    def get_customers():
        with get_connection() as conn:
            return conn.execute("SELECT id, name FROM customers ORDER BY name").fetchall()

    @staticmethod
    def generate_invoice_no():
        from services import setting
        prefix = setting("invoice_prefix", "INV") or "INV"
        with get_connection() as conn:
            rows = conn.execute("SELECT invoice_no FROM sales ORDER BY id DESC").fetchall()
        largest = 0
        for (invoice,) in rows:
            try:
                largest = max(largest, int(invoice.split("-")[-1]))
            except (ValueError, AttributeError):
                continue
        return f"{prefix}-{largest + 1:05d}"

    @staticmethod
    def available_stock(exclude_sale_id=None):
        return mushroom_stock(exclude_sale_id=exclude_sale_id)

    def new_sale(self, sale_id=None):
        old = None
        if sale_id is not None:
            with get_connection() as conn:
                old = conn.execute("""
                    SELECT invoice_no, sale_date, customer_id, quantity_kg,
                           rate_per_kg, discount, paid_amount, payment_mode, notes
                    FROM sales WHERE id=?
                """, (sale_id,)).fetchone()
            if not old:
                return

        window = tk.Toplevel(self.parent)
        window.title("Edit Sale" if old else "New Sale")
        window.geometry("600x700")
        window.resizable(False, False)
        window.transient(self.frame.winfo_toplevel())
        tk.Label(window, text="🧾 Edit Sale" if old else "🧾 New Sale", font=("Arial", 18, "bold")).pack(pady=15)
        form = tk.Frame(window)
        form.pack(fill="x", padx=30)

        entries = {}
        defaults = {
            "Invoice No.": old[0] if old else self.generate_invoice_no(),
            "Sale Date": old[1] if old else date.today().isoformat(),
            "Quantity (Kg)": old[3] if old else "",
            "Rate / Kg": old[4] if old else "",
            "Discount": old[5] if old else 0,
            "Paid Amount": old[6] if old else 0,
            "Notes": old[8] if old and old[8] else "",
        }
        row = 0
        for label in ("Invoice No.", "Sale Date"):
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=7)
            entry = tk.Entry(form, width=35)
            entry.insert(0, str(defaults[label]))
            entry.grid(row=row, column=1, pady=7)
            entries[label] = entry
            row += 1

        customers = self.get_customers()
        customer_ids = [None] + [item[0] for item in customers]
        customer_names = ["Cash Customer"] + [item[1] for item in customers]
        tk.Label(form, text="Customer").grid(row=row, column=0, sticky="w", pady=7)
        customer = ttk.Combobox(form, values=customer_names, state="readonly", width=32)
        customer.grid(row=row, column=1, pady=7)
        customer.current(0)
        if old and old[2] in customer_ids:
            customer.current(customer_ids.index(old[2]))
        row += 1

        for label in ("Quantity (Kg)", "Rate / Kg", "Discount", "Paid Amount"):
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=7)
            entry = tk.Entry(form, width=35)
            entry.insert(0, str(defaults[label]))
            entry.grid(row=row, column=1, pady=7)
            entries[label] = entry
            row += 1

        total_var, due_var = tk.StringVar(value="₹0.00"), tk.StringVar(value="₹0.00")
        for label, variable in (("Total Amount", total_var), ("Due Amount", due_var)):
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=7)
            tk.Label(form, textvariable=variable, font=("Arial", 13, "bold")).grid(row=row, column=1, sticky="w", pady=7)
            row += 1

        tk.Label(form, text="Payment Mode").grid(row=row, column=0, sticky="w", pady=7)
        payment = ttk.Combobox(form, values=("Cash", "UPI", "Bank", "Other", "Credit"), state="readonly", width=32)
        payment.grid(row=row, column=1, pady=7)
        payment.set(old[7] if old and old[7] else "Cash")
        row += 1
        tk.Label(form, text="Notes").grid(row=row, column=0, sticky="w", pady=7)
        notes = tk.Entry(form, width=35)
        notes.insert(0, str(defaults["Notes"]))
        notes.grid(row=row, column=1, pady=7)

        def calculate(event=None):
            try:
                total = float(entries["Quantity (Kg)"].get() or 0) * float(entries["Rate / Kg"].get() or 0) - float(entries["Discount"].get() or 0)
                due = total - float(entries["Paid Amount"].get() or 0)
                total_var.set(f"₹{total:,.2f}")
                due_var.set(f"₹{due:,.2f}")
            except ValueError:
                total_var.set("₹0.00")
                due_var.set("₹0.00")

        for label in ("Quantity (Kg)", "Rate / Kg", "Discount", "Paid Amount"):
            entries[label].bind("<KeyRelease>", calculate)
        calculate()

        def save():
            try:
                invoice = entries["Invoice No."].get().strip()
                sale_date = entries["Sale Date"].get().strip()
                qty = float(entries["Quantity (Kg)"].get())
                rate = float(entries["Rate / Kg"].get())
                discount = float(entries["Discount"].get() or 0)
                paid = float(entries["Paid Amount"].get() or 0)
                total = qty * rate - discount
                if not invoice or not sale_date or qty <= 0 or rate <= 0:
                    raise ValueError
                available = self.available_stock(sale_id)
                try: total=self.validate_sale(qty,rate,discount,paid,available)
                except OverflowError as error: messagebox.showerror("Insufficient Stock",str(error),parent=window);return
                customer_id = customer_ids[customer.current()] if customer.current() >= 0 else None
                values = (invoice, sale_date, customer_id, qty, rate, discount, total, paid, payment.get(), notes.get().strip())
                with get_connection() as conn:
                    if old:
                        conn.execute("""
                            UPDATE sales SET invoice_no=?, sale_date=?, customer_id=?, quantity_kg=?,
                            rate_per_kg=?, discount=?, total_amount=?, paid_amount=?, payment_mode=?, notes=?
                            WHERE id=?
                        """, values + (sale_id,))
                    else:
                        conn.execute("""
                            INSERT INTO sales (invoice_no, sale_date, customer_id, quantity_kg,
                            rate_per_kg, discount, total_amount, paid_amount, payment_mode, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, values)
                messagebox.showinfo("Success", "Sale saved successfully!", parent=window)
                window.destroy()
                self.load_sales()
            except ValueError:
                messagebox.showerror("Error", "সব required ও numeric field সঠিকভাবে দিন।", parent=window)
            except sqlite3.IntegrityError:
                messagebox.showerror("Error", "Invoice No. আগে ব্যবহার করা হয়েছে।", parent=window)
            except sqlite3.Error as error:
                messagebox.showerror("Database Error", str(error), parent=window)

        tk.Button(window, text="💾 Save Sale", command=save, bg="#27ae60", fg="white", font=("Arial", 11, "bold"), padx=30, pady=8).pack(pady=20)

    def _selected_values(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Warning", "একটি sale select করুন।", parent=self.frame)
            return None
        return self.tree.item(selected[0], "values")

    def edit_sale(self):
        values = self._selected_values()
        if values:
            self.new_sale(int(values[0]))

    def delete_sale(self):
        values = self._selected_values()
        if not values or not messagebox.askyesno("Confirm Delete", "এই sale delete করতে চান?", parent=self.frame):
            return
        with get_connection() as conn:
            conn.execute("DELETE FROM sales WHERE id=?", (values[0],))
        self.load_sales()

    def view_invoice(self):
        values = self._selected_values()
        if not values:
            return
        window = tk.Toplevel(self.parent)
        window.title(f"Invoice - {values[1]}")
        window.geometry("500x600")
        invoice = tk.Frame(window, bg="white", padx=30, pady=30)
        invoice.pack(fill="both", expand=True)
        tk.Label(invoice, text="🍄 OYSTER MUSHROOM", font=("Arial", 20, "bold"), bg="white").pack()
        tk.Label(invoice, text="SALES INVOICE", font=("Arial", 14), bg="white").pack(pady=5)
        ttk.Separator(invoice).pack(fill="x", pady=15)
        labels = ("Invoice No.", "Date", "Customer", "Quantity", "Rate", "Discount", "Total", "Paid", "Due", "Payment")
        shown = (values[1], values[2], values[3], f"{values[4]} Kg", values[5], values[6], values[7], values[8], values[9], values[10])
        for label, value in zip(labels, shown):
            line = tk.Frame(invoice, bg="white")
            line.pack(fill="x", pady=5)
            tk.Label(line, text=label, font=("Arial", 10, "bold"), bg="white", width=15, anchor="w").pack(side="left")
            tk.Label(line, text=value, bg="white", anchor="w").pack(side="left")
        ttk.Separator(invoice).pack(fill="x", pady=20)
        tk.Label(invoice, text="Thank You!", font=("Arial", 13, "bold"), bg="white").pack()

    def save_invoice_pdf(self):
        values = self._selected_values()
        if not values:
            return
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except ImportError:
            messagebox.showerror("ReportLab Missing", "PDF-এর জন্য install করুন: pip install reportlab", parent=self.frame)
            return
        from tkinter import filedialog
        from services import setting
        path = filedialog.asksaveasfilename(initialfile=f"{values[1]}.pdf", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        pdf=canvas.Canvas(path,pagesize=A4); width,height=A4; y=height-55
        pdf.setFont("Helvetica-Bold",18);pdf.drawCentredString(width/2,y,setting("business_name","Oyster Mushroom Business"));y-=24
        pdf.setFont("Helvetica",10)
        for line in (setting("address"),f"Mobile: {setting('mobile')}  Email: {setting('email')}",f"GSTIN: {setting('gstin')}"):
            if line:pdf.drawCentredString(width/2,y,line);y-=15
        y-=15;pdf.setFont("Helvetica-Bold",15);pdf.drawString(55,y,"SALES INVOICE");y-=28;pdf.setFont("Helvetica",11)
        labels=("Invoice No","Date","Customer","Quantity","Rate/Kg","Discount","Grand Total","Paid","Due","Payment Mode")
        shown=(values[1],values[2],values[3],f"{values[4]} Kg",values[5],values[6],values[7],values[8],values[9],values[10])
        for label,value in zip(labels,shown):pdf.drawString(60,y,f"{label}: {value}");y-=22
        pdf.setFont("Helvetica-Bold",12);pdf.drawCentredString(width/2,80,"Thank You!");pdf.save()
        messagebox.showinfo("PDF",f"Invoice saved:\n{path}",parent=self.frame)

    def show(self):
        self.frame.pack(fill="both", expand=True)
        self.load_sales()

    def hide(self):
        self.frame.pack_forget()
