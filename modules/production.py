import sqlite3
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from database import get_connection


class ProductionPage:
    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg="#f3f4f6")
        self.show_page()

    def show_page(self):
        for widget in self.frame.winfo_children():
            widget.destroy()

        tk.Label(
            self.frame, text="🌱 Production Management",
            font=("Arial", 24, "bold"), bg="#f3f4f6"
        ).pack(anchor="w", padx=30, pady=(25, 5))
        tk.Label(
            self.frame, text="Batch and Daily Production Management",
            font=("Arial", 11), bg="#f3f4f6", fg="#6b7280"
        ).pack(anchor="w", padx=32)

        buttons = tk.Frame(self.frame, bg="#f3f4f6")
        buttons.pack(fill="x", padx=30, pady=20)
        tk.Button(
            buttons, text="➕ New Batch", font=("Arial", 11, "bold"),
            command=self.new_batch, padx=20, pady=10
        ).pack(side="left", padx=5)
        tk.Button(
            buttons, text="🍄 Daily Production", font=("Arial", 11, "bold"),
            command=self.daily_production, padx=20, pady=10
        ).pack(side="left", padx=5)
        tk.Button(
            buttons, text="🔄 Refresh", font=("Arial", 11),
            command=self.show_batch_list, padx=20, pady=10
        ).pack(side="left", padx=5)

        self.list_area = tk.Frame(self.frame, bg="#f3f4f6")
        self.list_area.pack(fill="both", expand=True)
        self.show_batch_list()

    def show_batch_list(self):
        for widget in self.list_area.winfo_children():
            widget.destroy()

        tk.Label(
            self.list_area, text="Batch List", font=("Arial", 16, "bold"),
            bg="#f3f4f6"
        ).pack(anchor="w", padx=30, pady=10)

        table_frame = tk.Frame(self.list_area, bg="white")
        table_frame.pack(fill="both", expand=True, padx=30, pady=10)
        columns = (
            "Batch No", "Date", "Bags", "Straw", "Spawn",
            "Expected Yield", "Status"
        )
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=120, anchor="center")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        with get_connection() as conn:
            rows = conn.execute("""
                SELECT batch_no, production_date, bag_count, straw_qty,
                       spawn_qty, expected_yield, status
                FROM batches ORDER BY id DESC
            """).fetchall()
        for row in rows:
            tree.insert("", "end", values=row)

    @staticmethod
    def _entry(form, label):
        tk.Label(form, text=label, font=("Arial", 10)).pack(anchor="w", pady=(8, 2))
        entry = tk.Entry(form, font=("Arial", 11))
        entry.pack(fill="x", pady=2)
        return entry

    def new_batch(self):
        window = tk.Toplevel(self.frame)
        window.title("New Batch")
        window.geometry("500x650")
        window.resizable(False, False)
        window.transient(self.frame.winfo_toplevel())

        tk.Label(window, text="🌱 New Mushroom Batch", font=("Arial", 20, "bold")).pack(pady=20)
        form = tk.Frame(window)
        form.pack(padx=30, fill="x")
        labels = {
            "batch_no": "Batch No.", "production_date": "Production Date",
            "straw_qty": "Straw Quantity (Kg)", "spawn_qty": "Spawn Quantity (Kg)",
            "bag_count": "Number of Bags", "expected_yield": "Expected Yield (Kg)",
            "expected_harvest_date": "Expected Harvest Date"
        }
        entries = {key: self._entry(form, label) for key, label in labels.items()}
        entries["production_date"].insert(0, date.today().isoformat())

        tk.Label(form, text="Status", font=("Arial", 10)).pack(anchor="w", pady=(8, 2))
        status_var = tk.StringVar(value="Preparing")
        ttk.Combobox(
            form, textvariable=status_var,
            values=("Preparing", "Incubation", "Fruiting", "Harvesting", "Completed", "Failed"),
            state="readonly"
        ).pack(fill="x")

        def save_batch():
            try:
                batch_no = entries["batch_no"].get().strip()
                production_date = entries["production_date"].get().strip()
                if not batch_no or not production_date:
                    messagebox.showerror("Error", "Batch No. এবং Production Date দিন।", parent=window)
                    return
                values = (
                    batch_no, production_date,
                    float(entries["straw_qty"].get() or 0),
                    float(entries["spawn_qty"].get() or 0),
                    int(entries["bag_count"].get() or 0),
                    float(entries["expected_yield"].get() or 0),
                    entries["expected_harvest_date"].get().strip() or None,
                    status_var.get(),
                )
                if any(value < 0 for value in values[2:6]):
                    raise ValueError
                with get_connection() as conn:
                    conn.execute("""
                        INSERT INTO batches (
                            batch_no, production_date, straw_qty, spawn_qty,
                            bag_count, expected_yield, expected_harvest_date, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, values)
                messagebox.showinfo("Success", f"Batch {batch_no} saved successfully!", parent=window)
                window.destroy()
                self.show_batch_list()
            except ValueError:
                messagebox.showerror("Error", "Quantity এবং Bags-এর সঠিক non-negative সংখ্যা দিন।", parent=window)
            except sqlite3.IntegrityError:
                messagebox.showerror("Error", "এই Batch No. আগে ব্যবহার করা হয়েছে।", parent=window)
            except sqlite3.Error as error:
                messagebox.showerror("Database Error", str(error), parent=window)

        tk.Button(
            window, text="💾 Save Batch", font=("Arial", 12, "bold"),
            command=save_batch, padx=30, pady=10
        ).pack(pady=25)

    def daily_production(self):
        window = tk.Toplevel(self.frame)
        window.title("Daily Production")
        window.geometry("500x600")
        window.resizable(False, False)
        window.transient(self.frame.winfo_toplevel())

        tk.Label(window, text="🍄 Daily Production Entry", font=("Arial", 20, "bold")).pack(pady=20)
        form = tk.Frame(window)
        form.pack(padx=30, fill="x")
        production_date = self._entry(form, "Production Date")
        production_date.insert(0, date.today().isoformat())

        tk.Label(form, text="Batch No.", font=("Arial", 10)).pack(anchor="w", pady=(8, 2))
        with get_connection() as conn:
            batch_numbers = [row[0] for row in conn.execute("SELECT batch_no FROM batches ORDER BY id DESC")]
        batch_no = ttk.Combobox(form, values=batch_numbers, font=("Arial", 11))
        batch_no.pack(fill="x")
        bags = self._entry(form, "Bags")
        production_kg = self._entry(form, "Production (Kg)")
        wastage_kg = self._entry(form, "Wastage (Kg)")

        tk.Label(form, text="Saleable Kg", font=("Arial", 10)).pack(anchor="w", pady=(12, 2))
        saleable_label = tk.Label(form, text="0.00 Kg", font=("Arial", 16, "bold"))
        saleable_label.pack(anchor="w")

        def calculate_saleable(event=None):
            try:
                value = max(0, float(production_kg.get() or 0) - float(wastage_kg.get() or 0))
                saleable_label.config(text=f"{value:.2f} Kg")
            except ValueError:
                saleable_label.config(text="0.00 Kg")

        production_kg.bind("<KeyRelease>", calculate_saleable)
        wastage_kg.bind("<KeyRelease>", calculate_saleable)

        def save_production():
            try:
                values = (
                    production_date.get().strip(), batch_no.get().strip(),
                    int(bags.get() or 0), float(production_kg.get() or 0),
                    float(wastage_kg.get() or 0)
                )
                if not values[0] or not values[1]:
                    messagebox.showerror("Error", "Production Date এবং Batch No. দিন।", parent=window)
                    return
                if values[1] not in batch_numbers:
                    messagebox.showerror("Error", "Batch List থেকে একটি Batch No. নির্বাচন করুন।", parent=window)
                    return
                if any(value < 0 for value in values[2:]) or values[4] > values[3]:
                    messagebox.showerror("Error", "Production, wastage ও bags-এর সঠিক পরিমাণ দিন।", parent=window)
                    return
                saleable_kg = values[3] - values[4]
                with get_connection() as conn:
                    conn.execute("""
                        INSERT INTO daily_production (
                            production_date, batch_no, bags, production_kg,
                            wastage_kg, saleable_kg
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, values + (saleable_kg,))
                messagebox.showinfo("Success", "Daily production saved successfully!", parent=window)
                window.destroy()
            except ValueError:
                messagebox.showerror("Error", "সঠিক সংখ্যা দিন।", parent=window)
            except sqlite3.Error as error:
                messagebox.showerror("Database Error", str(error), parent=window)

        tk.Button(
            window, text="💾 Save Production", font=("Arial", 12, "bold"),
            command=save_production, padx=30, pady=10
        ).pack(pady=30)

    def show(self):
        self.frame.pack(fill="both", expand=True)

    def hide(self):
        self.frame.pack_forget()
