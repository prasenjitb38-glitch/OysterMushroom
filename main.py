import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from database import create_database, get_connection
from modules.harvest import HarvestPage
from modules.backup import BackupPage
from modules.batch_cost import BatchCostPage
from modules.charts import ChartsPage
from modules.customers import CustomerPage
from modules.expenses import ExpensePage
from modules.labour import LabourPage
from modules.ledger import LedgerPage
from modules.payments import PaymentPage
from modules.profit_loss import PnLPage
from modules.production import ProductionPage
from modules.purchases import PurchasePage, RawMaterialPage
from modules.sales import SalesPage
from modules.stock import StockPage
from modules.suppliers import SupplierPage
from modules.reports import ReportsPage
from modules.settings import SettingsPage
from modules.users import UsersPage
from modules.system_tools import authenticate,ChangePasswordPage
from services import require_permission,set_desktop_role
from services import customer_outstanding, labour_due, mushroom_stock, pnl, supplier_outstanding,low_stock_materials
from ui_theme import COLORS, configure_theme, polish_widgets
from events import subscribe,unsubscribe


create_database()


class MushroomApp:
    def __init__(self, root, user=None):
        self.root = root
        self.user = user or {"username": "admin", "role": "ADMIN", "name": "Administrator"}
        set_desktop_role(self.user.get("role"))
        configure_theme(self.root)
        self.root.title("Oyster Mushroom Business Manager")
        self.root.geometry("1200x700")
        self.root.minsize(1000, 600)

        self.create_sidebar()
        self.create_dashboard()
        subscribe(self._data_changed);self.root.bind("<Destroy>",lambda e:unsubscribe(self._data_changed) if e.widget is self.root else None)
        self.root.after_idle(lambda: polish_widgets(self.root))

    def create_sidebar(self):
        self.sidebar = tk.Frame(self.root, width=230, bg=COLORS["navy"], relief="raised", bd=3)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        canvas = tk.Canvas(self.sidebar, bg=COLORS["navy"], highlightthickness=0, width=210)
        scrollbar = ttk.Scrollbar(self.sidebar, orient="vertical", command=canvas.yview)
        menu = tk.Frame(canvas, bg=COLORS["navy"])
        window_id = canvas.create_window((0, 0), window=menu, anchor="nw")
        menu.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        title = tk.Label(
            menu,
            text="🍄\nOYSTER\nMUSHROOM",
            font=("Arial", 20, "bold"),
            bg=COLORS["navy"],
            fg="white",
        )
        title.pack(pady=15)

        buttons = [
            ("🏠  Dashboard", self.show_dashboard),
            ("🌱  Production", self.production),
            ("🍄  Harvest", self.harvest),
            ("📦  Stock", self.stock),
            ("🛒  Sales", self.sales),
            ("💰  Expenses", self.expenses),
            ("👥  Customers", self.customers),
            ("🚚  Suppliers", self.suppliers),
            ("👷  Labour", self.labour),
            ("🧺  Purchases", self.purchases),
            ("🧪  Raw Materials", self.raw_materials),
            ("💳  Payments", self.payments),
            ("🏦  Cash / Bank", self.ledger),
            ("🧾  Batch Cost", self.batch_cost),
            ("📈  Profit & Loss", self.profit_loss),
            ("📊  Reports", self.reports),
            ("📉  Charts", self.charts),
            ("💾  Backup/Restore", self.backup_restore),
            ("⚙️  Settings", self.settings),
            ("🔐  Users", self.users),
            ("🔑  Change Password", self.change_password),
            ("↪  Logout", self.logout),
        ]

        if self.user.get("role") == "STAFF":
            hidden = {"Suppliers", "Labour", "Purchases", "Raw Materials", "Payments", "Cash / Bank", "Batch Cost", "Profit & Loss", "Backup/Restore", "Settings", "Users"}
            buttons = [(text, command) for text, command in buttons if not any(name in text for name in hidden)]
        elif self.user.get("role") == "MANAGER":
            buttons = [(text, command) for text, command in buttons if not any(name in text for name in ("Backup/Restore", "Settings", "Users"))]

        for text, command in buttons:
            button = tk.Button(
                menu,
                text=text,
                command=command,
                anchor="w",
                font=("Arial", 9),
                bg=COLORS["navy_light"],
                fg="white",
                activebackground="#365274",
                activeforeground="white",
                relief="raised",
                bd=1,
                padx=20,
                pady=5,
            )
            button.pack(fill="x", padx=10, pady=2)

    def create_dashboard(self):
        self.main_area = tk.Frame(self.root, bg="#f3f4f6")
        self.main_area.pack(side="right", fill="both", expand=True)
        self.show_dashboard()

    def clear_main(self):
        for widget in self.main_area.winfo_children():
            widget.destroy()
        self.root.after_idle(lambda: polish_widgets(self.main_area))

    def show_dashboard(self):
        self.current_page="dashboard"
        self.clear_main()

        with get_connection() as conn:
            today = date.today().isoformat()
            active_batches = conn.execute("""
                SELECT COUNT(*) FROM batches
                WHERE LOWER(COALESCE(status, '')) NOT IN ('completed', 'failed')
            """).fetchone()[0]
            total_production = conn.execute("""
                SELECT COALESCE(SUM(production_kg), 0) FROM daily_production
            """).fetchone()[0]
            total_bags = conn.execute("SELECT COALESCE(SUM(bag_count),0) FROM batches").fetchone()[0]
            today_production = conn.execute("SELECT COALESCE(SUM(production_kg),0) FROM daily_production WHERE production_date=?",(today,)).fetchone()[0]
            today_harvest, total_wastage = conn.execute("SELECT COALESCE(SUM(CASE WHEN harvest_date=? THEN quantity_kg ELSE 0 END),0),COALESCE(SUM(wastage_kg),0) FROM harvests",(today,)).fetchone()
            sold_kg, total_sales = conn.execute("""
                SELECT COALESCE(SUM(quantity_kg), 0),
                       COALESCE(SUM(total_amount), 0) FROM sales
            """).fetchone()
            today_sales = conn.execute("SELECT COALESCE(SUM(total_amount),0) FROM sales WHERE sale_date=?",(today,)).fetchone()[0]
            total_expense = conn.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM expenses
            """).fetchone()[0]
            recent_rows = conn.execute("""
                SELECT production_date, batch_no, bags, production_kg,
                       wastage_kg, saleable_kg
                FROM daily_production
                ORDER BY production_date DESC, id DESC
                LIMIT 10
            """).fetchall()

        current_stock = mushroom_stock()
        profit = pnl()
        net_profit = profit["net"]
        customer_due = customer_outstanding()
        supplier_due = supplier_outstanding()
        worker_due = labour_due()
        low_materials=low_stock_materials()

        heading = tk.Frame(self.main_area, bg="#f3f4f6")
        heading.pack(fill="x", padx=30, pady=(25, 5))
        tk.Label(
            heading,
            text="🍄 OYSTER MUSHROOM BUSINESS MANAGER",
            font=("Arial", 26, "bold"),
            bg="#f3f4f6",
        ).pack(side="left")
        tk.Button(
            heading,
            text="🔄 Refresh",
            command=self.show_dashboard,
            font=("Arial", 10, "bold"),
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=7,
        ).pack(side="right")

        tk.Label(
            self.main_area,
            text="Dashboard · Live Business Overview",
            font=("Arial", 11),
            bg="#f3f4f6",
            fg="#6b7280",
        ).pack(anchor="w", padx=32)

        cards_frame = tk.Frame(self.main_area, bg="#f3f4f6")
        cards_frame.pack(fill="x", padx=30, pady=20)

        cards = [
            ("🌱 Active Batch", f"{active_batches}"),
            ("🧺 Total Bags", f"{total_bags}"),
            ("🍄 Today's Production", f"{today_production:.2f} Kg"),
            ("🍄 Today's Harvest", f"{today_harvest:.2f} Kg"),
            ("🛒 Today's Sales", f"₹{today_sales:,.2f}"),
            ("📦 Current Stock", f"{current_stock:.2f} Kg"),
            ("🛒 Total Sales", f"₹{total_sales:,.2f}"),
            ("💸 Total Expense", f"₹{total_expense:,.2f}"),
            ("📊 Gross Profit", f"₹{profit['gross']:,.2f}"),
            ("📈 Net Profit", f"₹{net_profit:,.2f}"),
            ("👥 Customer Due", f"₹{customer_due:,.2f}"),
            ("🚚 Supplier Due", f"₹{supplier_due:,.2f}"),
            ("👷 Labour Due", f"₹{worker_due:,.2f}"),
            ("🗑 Wastage", f"{total_wastage:.2f} Kg"),
        ]

        for index, (title, value) in enumerate(cards):
            card = tk.Frame(
                cards_frame, bg="white", bd=1, relief="solid",
                highlightbackground="#d1d5db", highlightthickness=1
            )
            card.grid(
                row=index // 4,
                column=index % 4,
                padx=8,
                pady=8,
                sticky="nsew",
            )
            cards_frame.columnconfigure(index % 4, weight=1)

            tk.Label(
                card,
                text=title,
                font=("Arial", 11),
                bg="white",
                fg="#6b7280",
            ).pack(anchor="w", padx=12, pady=(8, 2))

            tk.Label(
                card,
                text=value,
                font=("Arial", 15, "bold"),
                bg="white",
            ).pack(anchor="w", padx=12, pady=(0, 8))

        recent = tk.LabelFrame(
            self.main_area,
            text="  Recent Production  ",
            font=("Arial", 12, "bold"),
            bg="white",
            padx=15,
            pady=15,
        )
        recent.pack(fill="both", expand=True, padx=30, pady=15)

        columns = ("Date", "Batch", "Bags", "Production", "Wastage", "Saleable")
        tree = ttk.Treeview(recent, columns=columns, show="headings", height=8)
        for column in columns:
            tree.heading(column, text=column)
            tree.column(column, width=120, anchor="center")
        scrollbar = ttk.Scrollbar(recent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        for row in recent_rows:
            tree.insert("", "end", values=(
                row[0], row[1], row[2], f"{row[3]:.2f} Kg",
                f"{row[4]:.2f} Kg", f"{row[5]:.2f} Kg"
            ))

        if not recent_rows:
            tree.insert("", "end", values=("No production data available yet.", "", "", "", "", ""))
        if low_materials:
            tk.Label(self.main_area,text="⚠ Low Stock: "+", ".join(f"{r[1]} ({r[3]:.2f} {r[2]})" for r in low_materials),bg="#fff3cd",fg="#856404",font=("Arial",10,"bold"),anchor="w").pack(fill="x",padx=30,pady=5)
    def _data_changed(self,event):
        if getattr(self,"current_page",None)=="dashboard":self.root.after_idle(self.show_dashboard)

    def page_message(self, title):
        self.clear_main()
        tk.Label(
            self.main_area,
            text=title,
            font=("Arial", 26, "bold"),
            bg="#f3f4f6",
        ).pack(anchor="w", padx=30, pady=30)
        tk.Label(
            self.main_area,
            text="This module will be developed in the next step.",
            font=("Arial", 14),
            bg="#f3f4f6",
            fg="#6b7280",
        ).pack(anchor="w", padx=32)

    def production(self):
        self.clear_main()

        production_page = ProductionPage(
            self.main_area
        )

        production_page.show()

    def harvest(self):
        self.clear_main()

        harvest_page = HarvestPage(
            self.main_area
        )

        harvest_page.show()

    def stock(self):
        self.clear_main()

        self.stock_page = StockPage(
            self.main_area
        )

        self.stock_page.show()

    def sales(self):
        self.clear_main()

        self.sales_page = SalesPage(
            self.main_area
        )

        self.sales_page.show()

    def expenses(self):
        self.clear_main()
        self.expense_page = ExpensePage(self.main_area)
        self.expense_page.show()

    def customers(self):
        self.clear_main()
        self.customer_page = CustomerPage(self.main_area)
        self.customer_page.show()

    def suppliers(self):
        self.clear_main()
        self.supplier_page = SupplierPage(self.main_area)
        self.supplier_page.show()

    def labour(self):
        self.clear_main()
        self.labour_page = LabourPage(self.main_area)
        self.labour_page.show()

    def purchases(self):
        self.clear_main()
        self.purchase_page = PurchasePage(self.main_area)
        self.purchase_page.show()

    def raw_materials(self):
        self.clear_main()
        self.raw_material_page = RawMaterialPage(self.main_area)
        self.raw_material_page.show()

    def payments(self):
        self.clear_main()
        self.payment_page = PaymentPage(self.main_area)
        self.payment_page.show()

    def ledger(self):
        self.clear_main()
        self.ledger_page = LedgerPage(self.main_area)
        self.ledger_page.show()

    def reports(self):
        self.clear_main(); self.reports_page = ReportsPage(self.main_area); self.reports_page.show()

    def batch_cost(self):
        self.clear_main(); self.batch_cost_page = BatchCostPage(self.main_area); self.batch_cost_page.show()

    def profit_loss(self):
        self.clear_main(); self.pnl_page = PnLPage(self.main_area); self.pnl_page.show()

    def charts(self):
        self.clear_main(); self.charts_page = ChartsPage(self.main_area); self.charts_page.show()

    def backup_restore(self):
        self.clear_main(); self.backup_page = BackupPage(self.main_area); self.backup_page.show()

    def settings(self):
        self.clear_main(); self.settings_page = SettingsPage(self.main_area); self.settings_page.show()

    def users(self):
        try:require_permission(self.user.get("role"),"users")
        except PermissionError:return messagebox.showerror("Forbidden","Admin permission required.",parent=self.root)
        self.clear_main(); self.users_page = UsersPage(self.main_area,self.user); self.users_page.show()
    def change_password(self):
        self.clear_main();self.change_password_page=ChangePasswordPage(self.main_area,self.user);self.change_password_page.show()
    def logout(self):
        self.root.destroy()


def login_dialog(root):
    result = {}
    window = tk.Toplevel(root); window.title("Login"); window.geometry("380x300"); window.resizable(False, False); window.grab_set()
    tk.Label(window,text="🍄 Oyster Mushroom Login",font=("Arial",18,"bold")).pack(pady=25)
    tk.Label(window,text="Username").pack(); username=tk.Entry(window);username.pack();username.insert(0,"admin")
    tk.Label(window,text="Password").pack(pady=(10,0));password=tk.Entry(window,show="*");password.pack()
    def submit():
        row=authenticate(username.get().strip(),password.get())
        if not row:messagebox.showerror("Login Failed","Username/password সঠিক নয়।",parent=window);return
        result.update({"id":row[0],"username":username.get().strip(),"role":row[2],"name":row[4],"must_change_password":bool(row[5])});window.destroy()
    tk.Button(window,text="Login",command=submit,bg="#2563eb",fg="white",padx=30,pady=7).pack(pady=22)
    window.protocol("WM_DELETE_WINDOW",lambda:(window.destroy(),root.destroy()))
    root.wait_window(window);return result or None


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    logged_in = login_dialog(root)
    if logged_in:
        root.deiconify()
        app = MushroomApp(root, logged_in)
        if logged_in.get("must_change_password"):root.after(100,app.change_password)
        root.mainloop()
