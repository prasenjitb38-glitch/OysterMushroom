import sqlite3
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from database import get_connection
from events import publish


class HarvestPage:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg="#f3f4f6")
        self.show_page()

    def show_page(self):
        for widget in self.frame.winfo_children():
            widget.destroy()

        tk.Label(
            self.frame, text="🍄 Harvest Management",
            font=("Arial", 24, "bold"), bg="#f3f4f6"
        ).pack(anchor="w", padx=30, pady=(25, 5))
        tk.Label(
            self.frame, text="Flush-wise Mushroom Harvest Management",
            font=("Arial", 11), bg="#f3f4f6", fg="#6b7280"
        ).pack(anchor="w", padx=32)

        buttons = tk.Frame(self.frame, bg="#f3f4f6")
        buttons.pack(fill="x", padx=30, pady=20)
        tk.Button(
            buttons, text="➕ New Harvest", font=("Arial", 11, "bold"),
            command=self.new_harvest, padx=20, pady=10
        ).pack(side="left", padx=5)
        tk.Button(
            buttons, text="🔄 Refresh", command=self.show_page,
            padx=20, pady=10
        ).pack(side="left", padx=5)

        self.notebook = ttk.Notebook(self.frame)
        self.notebook.pack(fill="both", expand=True, padx=30, pady=10)
        self.harvest_tab = tk.Frame(self.notebook, bg="white")
        self.summary_tab = tk.Frame(self.notebook, bg="white")
        self.notebook.add(self.harvest_tab, text="  🍄 Harvest Records  ")
        self.notebook.add(self.summary_tab, text="  📊 Harvest Summary  ")
        self.show_harvest_records()
        self.show_summary()

    @staticmethod
    def _flush_name(number):
        suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
        return f"{number}{suffix} Flush"

    @staticmethod
    def _card(parent, title, value):
        frame = tk.Frame(parent, bg="#f9fafb", bd=1, relief="solid")
        tk.Label(frame, text=title, font=("Arial", 10), bg="#f9fafb", fg="#6b7280").pack(pady=(10, 2))
        tk.Label(frame, text=value, font=("Arial", 16, "bold"), bg="#f9fafb").pack(pady=(0, 10))
        return frame

    def show_harvest_records(self):
        for widget in self.harvest_tab.winfo_children():
            widget.destroy()

        tk.Label(
            self.harvest_tab, text="Harvest Records", font=("Arial", 16, "bold"), bg="white"
        ).pack(anchor="w", padx=20, pady=15)

        with get_connection() as conn:
            total, wastage = conn.execute("""
                SELECT COALESCE(SUM(quantity_kg), 0), COALESCE(SUM(wastage_kg), 0)
                FROM harvests
            """).fetchone()

        cards = tk.Frame(self.harvest_tab, bg="white")
        cards.pack(fill="x", padx=20)
        for title, value in (
            ("🍄 Total Harvest", total), ("❌ Wastage", wastage),
            ("📦 Saleable", total - wastage)
        ):
            self._card(cards, title, f"{value:.2f} Kg").pack(side="left", fill="x", expand=True, padx=5)

        table_frame = tk.Frame(self.harvest_tab, bg="white")
        table_frame.pack(fill="both", expand=True, padx=20, pady=15)
        columns = ("ID", "Date", "Batch", "Flush", "Harvest Kg", "Wastage Kg", "Saleable Kg", "Grade")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        widths = (55, 105, 90, 100, 105, 105, 105, 70)
        for column, width in zip(columns, widths):
            self.tree.heading(column, text=column)
            self.tree.column(column, width=width, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.load_records()

        actions = tk.Frame(self.harvest_tab, bg="white")
        actions.pack(fill="x", padx=20, pady=(0, 15))
        tk.Button(actions, text="✏️ Edit", command=self.edit_harvest, padx=20, pady=8).pack(side="left", padx=5)
        tk.Button(actions, text="🗑 Delete", command=self.delete_harvest, padx=20, pady=8).pack(side="left", padx=5)

    def load_records(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT id, harvest_date, batch_no, flush_no, quantity_kg,
                       wastage_kg, grade FROM harvests
                ORDER BY harvest_date DESC, id DESC
            """).fetchall()
        for record_id, harvest_date, batch_no, flush_no, quantity, wastage, grade in rows:
            quantity, wastage = quantity or 0, wastage or 0
            self.tree.insert("", "end", values=(
                record_id, harvest_date, batch_no, self._flush_name(flush_no),
                f"{quantity:.2f}", f"{wastage:.2f}", f"{quantity - wastage:.2f}", grade or ""
            ))

    @staticmethod
    def _batches():
        with get_connection() as conn:
            return [row[0] for row in conn.execute("SELECT batch_no FROM batches ORDER BY id DESC")]

    @staticmethod
    def _label(form, text):
        tk.Label(form, text=text).pack(anchor="w", pady=(8, 2))

    def _harvest_window(self, title, record=None):
        window = tk.Toplevel(self.frame)
        window.title(title)
        window.geometry("520x700")
        window.resizable(False, False)
        window.transient(self.frame.winfo_toplevel())
        tk.Label(window, text=f"🍄 {title}", font=("Arial", 20, "bold")).pack(pady=20)
        form = tk.Frame(window)
        form.pack(padx=35, fill="x")

        defaults = record or (None, date.today().isoformat(), "", 1, 0, 0, "A", "")
        fields = {}
        for key, label, value in (
            ("date", "Harvest Date", defaults[1]),
            ("quantity", "Harvest Quantity (Kg)", defaults[4]),
            ("wastage", "Wastage (Kg)", defaults[5]),
        ):
            self._label(form, label)
            fields[key] = tk.Entry(form, font=("Arial", 11))
            fields[key].insert(0, str(value))
            fields[key].pack(fill="x")

        self._label(form, "Batch No.")
        batch_var = tk.StringVar(value=defaults[2])
        ttk.Combobox(form, textvariable=batch_var, values=self._batches(), state="readonly").pack(fill="x")
        self._label(form, "Flush No.")
        flush_var = tk.StringVar(value=str(defaults[3]))
        ttk.Combobox(form, textvariable=flush_var, values=("1", "2", "3", "4"), state="readonly").pack(fill="x")

        self._label(form, "Saleable Quantity")
        saleable = tk.Label(form, text="0.00 Kg", font=("Arial", 16, "bold"))
        saleable.pack(anchor="w")

        def calculate(event=None):
            try:
                saleable.config(text=f"{max(0, float(fields['quantity'].get() or 0) - float(fields['wastage'].get() or 0)):.2f} Kg")
            except ValueError:
                saleable.config(text="0.00 Kg")

        fields["quantity"].bind("<KeyRelease>", calculate)
        fields["wastage"].bind("<KeyRelease>", calculate)
        calculate()

        self._label(form, "Grade")
        grade_var = tk.StringVar(value=defaults[6] or "A")
        ttk.Combobox(form, textvariable=grade_var, values=("A", "B", "C"), state="readonly").pack(fill="x")
        self._label(form, "Notes")
        notes = tk.Entry(form, font=("Arial", 11))
        notes.insert(0, defaults[7] or "")
        notes.pack(fill="x")

        def save():
            try:
                harvest_date = fields["date"].get().strip()
                batch_no = batch_var.get().strip()
                quantity = float(fields["quantity"].get() or 0)
                wastage = float(fields["wastage"].get() or 0)
                if not harvest_date or not batch_no:
                    messagebox.showerror("Error", "Harvest Date এবং Batch No. দিন।", parent=window)
                    return
                if quantity < 0 or wastage < 0 or wastage > quantity:
                    messagebox.showerror("Error", "Harvest ও wastage-এর সঠিক non-negative পরিমাণ দিন।", parent=window)
                    return
                values = (harvest_date, batch_no, int(flush_var.get()), quantity, wastage, grade_var.get(), notes.get().strip())
                with get_connection() as conn:
                    exists = conn.execute("SELECT id FROM batches WHERE batch_no = ?", (batch_no,)).fetchone()
                    if not exists:
                        messagebox.showerror("Error", f"Batch '{batch_no}' পাওয়া যায়নি।", parent=window)
                        return
                    if record:
                        conn.execute("""
                            UPDATE harvests SET harvest_date=?, batch_no=?, flush_no=?,
                            quantity_kg=?, wastage_kg=?, grade=?, notes=?,batch_id=? WHERE id=?
                        """, values + (exists[0],record[0]))
                    else:
                        conn.execute("""
                            INSERT INTO harvests (harvest_date, batch_no, flush_no,
                            quantity_kg, wastage_kg, grade, notes,batch_id) VALUES (?, ?, ?, ?, ?, ?, ?,?)
                        """, values+(exists[0],))
                publish("harvest_changed")
                messagebox.showinfo("Success", "Harvest updated successfully!" if record else "Harvest saved successfully!", parent=window)
                window.destroy()
                self.show_harvest_records()
                self.show_summary()
            except ValueError:
                messagebox.showerror("Error", "সঠিক সংখ্যা দিন।", parent=window)
            except sqlite3.Error as error:
                messagebox.showerror("Database Error", str(error), parent=window)

        tk.Button(
            window, text="💾 Update" if record else "💾 Save Harvest",
            command=save, font=("Arial", 12, "bold"), padx=30, pady=10
        ).pack(pady=25)

    def new_harvest(self):
        self._harvest_window("New Harvest Entry")

    def edit_harvest(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Select Record", "একটি record select করুন।", parent=self.frame)
            return
        record_id = self.tree.item(selected[0])["values"][0]
        with get_connection() as conn:
            record = conn.execute("""
                SELECT id, harvest_date, batch_no, flush_no, quantity_kg,
                       wastage_kg, grade, notes FROM harvests WHERE id=?
            """, (record_id,)).fetchone()
        if record:
            self._harvest_window("Edit Harvest", record)

    def delete_harvest(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Select Record", "একটি record select করুন।", parent=self.frame)
            return
        record_id = self.tree.item(selected[0])["values"][0]
        if not messagebox.askyesno("Confirm Delete", "এই harvest record delete করবেন?", parent=self.frame):
            return
        with get_connection() as conn:
            conn.execute("DELETE FROM harvests WHERE id=?", (record_id,))
        publish("harvest_changed")
        self.show_harvest_records()
        self.show_summary()

    def _summary_table(self, parent, title, columns, rows):
        tk.Label(parent, text=title, font=("Arial", 16, "bold"), bg="white").pack(anchor="w", padx=20, pady=(15, 5))
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=6)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=145, anchor="center")
        for row in rows:
            tree.insert("", "end", values=row)
        tree.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    def show_summary(self):
        for widget in self.summary_tab.winfo_children():
            widget.destroy()
        with get_connection() as conn:
            batches = conn.execute("""
                SELECT batch_no, COALESCE(SUM(quantity_kg),0),
                       COALESCE(SUM(wastage_kg),0), COUNT(id)
                FROM harvests GROUP BY batch_no ORDER BY batch_no
            """).fetchall()
            flushes = conn.execute("""
                SELECT flush_no, COALESCE(SUM(quantity_kg),0),
                       COALESCE(SUM(wastage_kg),0), COUNT(id)
                FROM harvests GROUP BY flush_no ORDER BY flush_no
            """).fetchall()
        batch_rows = [(b, f"{t:.2f} Kg", f"{w:.2f} Kg", f"{t-w:.2f} Kg", c) for b, t, w, c in batches]
        flush_rows = [(self._flush_name(f), f"{t:.2f} Kg", f"{w:.2f} Kg", f"{t-w:.2f} Kg", c) for f, t, w, c in flushes]
        columns = ("Group", "Total Harvest", "Wastage", "Saleable", "Records")
        self._summary_table(self.summary_tab, "📊 Batch-wise Harvest Summary", columns, batch_rows)
        self._summary_table(self.summary_tab, "🍄 Flush-wise Harvest Summary", columns, flush_rows)

    def show(self):
        self.frame.pack(fill="both", expand=True)

    def hide(self):
        self.frame.pack_forget()
