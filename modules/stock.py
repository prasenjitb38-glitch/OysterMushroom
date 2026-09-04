import sqlite3
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from database import get_connection
from services import mushroom_stock, setting


class StockPage:
    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent, bg="#f5f6fa")
        self.create_ui()
        self.load_stock()

    def create_ui(self):
        title_frame = tk.Frame(self.frame, bg="#f5f6fa")
        title_frame.pack(fill="x", padx=20, pady=15)
        tk.Label(
            title_frame, text="🍄 Mushroom Stock Management",
            font=("Arial", 22, "bold"), bg="#f5f6fa"
        ).pack(side="left")
        tk.Button(
            title_frame, text="🔄 Refresh", command=self.load_stock,
            bg="#3498db", fg="white", font=("Arial", 10, "bold"), padx=15, pady=6
        ).pack(side="right")

        cards = tk.Frame(self.frame, bg="#f5f6fa")
        cards.pack(fill="x", padx=20)
        self.opening_label = self.create_card(cards, "📦 Opening/Adjustment", "0 Kg")
        self.harvest_label = self.create_card(cards, "🍄 Total Production", "0 Kg")
        self.sales_label = self.create_card(cards, "🛒 Total Sales", "0 Kg")
        self.wastage_label = self.create_card(cards, "🗑️ Wastage", "0 Kg")
        self.stock_label = self.create_card(cards, "📊 Current Stock", "0 Kg")

        buttons = tk.Frame(self.frame, bg="#f5f6fa")
        buttons.pack(fill="x", padx=20, pady=15)
        tk.Button(
            buttons, text="➕ Add Opening Stock", command=self.add_opening_stock,
            bg="#27ae60", fg="white", font=("Arial", 10, "bold"), padx=15, pady=7
        ).pack(side="left", padx=5)
        tk.Button(
            buttons, text="⚙️ Stock Adjustment", command=self.stock_adjustment,
            bg="#f39c12", fg="white", font=("Arial", 10, "bold"), padx=15, pady=7
        ).pack(side="left", padx=5)

        notebook = ttk.Notebook(self.frame)
        notebook.pack(fill="both", expand=True, padx=20, pady=10)
        self.ledger_tab = tk.Frame(notebook, bg="white")
        self.batch_tab = tk.Frame(notebook, bg="white")
        notebook.add(self.ledger_tab, text="📋 Stock Ledger")
        notebook.add(self.batch_tab, text="📊 Batch-wise Stock")
        self.ledger_tree = self.create_table(
            self.ledger_tab, ("ID", "Date", "Type", "Batch", "Quantity Kg", "Notes"),
            (55, 105, 130, 100, 110, 280)
        )
        self.batch_tree = self.create_table(
            self.batch_tab,
            ("Batch No", "Opening/Adjustment", "Production Kg", "Sales Kg", "Wastage Kg", "Current Stock Kg"),
            (120, 145, 120, 120, 120, 150)
        )

    @staticmethod
    def create_card(parent, title, value):
        frame = tk.Frame(parent, bg="white", bd=1, relief="solid", width=180, height=90)
        frame.pack(side="left", fill="both", expand=True, padx=5)
        frame.pack_propagate(False)
        tk.Label(frame, text=title, font=("Arial", 10), bg="white").pack(pady=(12, 3))
        label = tk.Label(frame, text=value, font=("Arial", 17, "bold"), bg="white")
        label.pack()
        return label

    @staticmethod
    def create_table(parent, columns, widths):
        holder = tk.Frame(parent, bg="white")
        holder.pack(fill="both", expand=True)
        tree = ttk.Treeview(holder, columns=columns, show="headings")
        for column, width in zip(columns, widths):
            tree.heading(column, text=column)
            tree.column(column, width=width, anchor="center")
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        return tree

    def load_stock(self):
        with get_connection() as conn:
            transaction_total = conn.execute(
                "SELECT COALESCE(SUM(quantity_kg), 0) FROM stock_transactions"
            ).fetchone()[0] or 0
            total_production, total_wastage = conn.execute("""
                SELECT COALESCE(SUM(quantity_kg), 0), COALESCE(SUM(wastage_kg), 0)
                FROM harvests
            """).fetchone()
            total_sales = conn.execute(
                "SELECT COALESCE(SUM(quantity_kg), 0) FROM sales"
            ).fetchone()[0] or 0
            transaction_total += float(setting("opening_mushroom_stock", "0") or 0)
            current_stock = mushroom_stock(conn)

            self.opening_label.config(text=f"{transaction_total:.2f} Kg")
            self.harvest_label.config(text=f"{total_production:.2f} Kg")
            self.sales_label.config(text=f"{total_sales:.2f} Kg")
            self.wastage_label.config(text=f"{total_wastage:.2f} Kg")
            self.stock_label.config(text=f"{current_stock:.2f} Kg")

            ledger = conn.execute("""
                SELECT source_id, entry_date, entry_type, batch_no, quantity_kg, notes
                FROM (
                    SELECT id AS source_id, transaction_date AS entry_date,
                           transaction_type AS entry_type, COALESCE(batch_no, '') AS batch_no,
                           quantity_kg, COALESCE(notes, '') AS notes
                    FROM stock_transactions
                    UNION ALL
                    SELECT id, harvest_date, 'Harvest', COALESCE(batch_no, ''),
                           quantity_kg-wastage_kg,
                           'Gross: ' || printf('%.2f', quantity_kg) ||
                           ' Kg; Wastage: ' || printf('%.2f', wastage_kg) || ' Kg'
                    FROM harvests
                    UNION ALL
                    SELECT id, sale_date, 'Sale', '', -quantity_kg, COALESCE(notes, '') FROM sales
                ) ORDER BY entry_date DESC, source_id DESC
            """).fetchall()

            batches = conn.execute("""
                SELECT batch_no FROM batches
                UNION SELECT batch_no FROM harvests WHERE batch_no IS NOT NULL AND batch_no != ''
                UNION SELECT batch_no FROM stock_transactions WHERE batch_no IS NOT NULL AND batch_no != ''
                ORDER BY batch_no
            """).fetchall()

            batch_rows = []
            for (batch_no,) in batches:
                adjustment = conn.execute("""
                    SELECT COALESCE(SUM(quantity_kg), 0) FROM stock_transactions WHERE batch_no=?
                """, (batch_no,)).fetchone()[0] or 0
                production, wastage = conn.execute("""
                    SELECT COALESCE(SUM(quantity_kg), 0), COALESCE(SUM(wastage_kg), 0)
                    FROM harvests WHERE batch_no=?
                """, (batch_no,)).fetchone()
                # Temporary bridge until the Sales module gets a dedicated batch_no column.
                sales = conn.execute("""
                    SELECT COALESCE(SUM(quantity_kg), 0) FROM sales WHERE notes LIKE ?
                """, (f"%{batch_no}%",)).fetchone()[0] or 0
                batch_rows.append((
                    batch_no, adjustment, production, sales, wastage,
                    adjustment + production - wastage - sales
                ))

        for tree in (self.ledger_tree, self.batch_tree):
            for item in tree.get_children():
                tree.delete(item)
        for row in ledger:
            self.ledger_tree.insert("", "end", values=row)
        for batch_no, adjustment, production, sales, wastage, stock in batch_rows:
            self.batch_tree.insert("", "end", values=(
                batch_no, f"{adjustment:.2f}", f"{production:.2f}", f"{sales:.2f}",
                f"{wastage:.2f}", f"{stock:.2f}"
            ))

    def _transaction_window(self, adjustment=False):
        window = tk.Toplevel(self.parent)
        window.title("Stock Adjustment" if adjustment else "Add Opening Stock")
        window.geometry("420x470" if adjustment else "420x420")
        window.resizable(False, False)
        window.transient(self.frame.winfo_toplevel())
        tk.Label(
            window, text="⚙️ Stock Adjustment" if adjustment else "➕ Add Opening Mushroom Stock",
            font=("Arial", 16, "bold")
        ).pack(pady=20)

        form = tk.Frame(window)
        form.pack(fill="x", padx=30)
        tk.Label(form, text="Date").pack(anchor="w")
        date_entry = tk.Entry(form)
        date_entry.insert(0, date.today().isoformat())
        date_entry.pack(fill="x", pady=5)

        batches = [row[0] for row in self._query("SELECT batch_no FROM batches ORDER BY id DESC")]
        tk.Label(form, text="Batch No. (optional)").pack(anchor="w", pady=(8, 0))
        batch = ttk.Combobox(form, values=batches)
        batch.pack(fill="x", pady=5)

        transaction_type = tk.StringVar(value="Adjustment In" if adjustment else "Opening")
        if adjustment:
            tk.Label(form, text="Adjustment Type").pack(anchor="w", pady=(8, 0))
            ttk.Combobox(
                form, textvariable=transaction_type,
                values=("Adjustment In", "Adjustment Out"), state="readonly"
            ).pack(fill="x", pady=5)

        tk.Label(form, text="Quantity (Kg)").pack(anchor="w", pady=(8, 0))
        quantity = tk.Entry(form)
        quantity.pack(fill="x", pady=5)
        tk.Label(form, text="Reason" if adjustment else "Notes").pack(anchor="w", pady=(8, 0))
        notes = tk.Entry(form)
        notes.pack(fill="x", pady=5)

        def save():
            try:
                value = float(quantity.get())
                if value <= 0 or not date_entry.get().strip():
                    raise ValueError
                signed_value = -value if transaction_type.get() == "Adjustment Out" else value
                with get_connection() as conn:
                    conn.execute("""
                        INSERT INTO stock_transactions (
                            transaction_date, transaction_type, batch_no, quantity_kg, notes
                        ) VALUES (?, ?, ?, ?, ?)
                    """, (
                        date_entry.get().strip(), transaction_type.get(),
                        batch.get().strip() or None, signed_value, notes.get().strip()
                    ))
                messagebox.showinfo("Success", "Stock transaction saved!", parent=window)
                window.destroy()
                self.load_stock()
            except ValueError:
                messagebox.showerror("Error", "Date এবং valid positive quantity দিন।", parent=window)
            except sqlite3.Error as error:
                messagebox.showerror("Database Error", str(error), parent=window)

        tk.Button(
            window, text="💾 Save Adjustment" if adjustment else "💾 Save",
            command=save, bg="#f39c12" if adjustment else "#27ae60", fg="white",
            font=("Arial", 10, "bold"), padx=25, pady=7
        ).pack(pady=25)

    @staticmethod
    def _query(sql, parameters=()):
        with get_connection() as conn:
            return conn.execute(sql, parameters).fetchall()

    def add_opening_stock(self):
        self._transaction_window(False)

    def stock_adjustment(self):
        self._transaction_window(True)

    def show(self):
        self.frame.pack(fill="both", expand=True)
        self.load_stock()

    def hide(self):
        self.frame.pack_forget()
