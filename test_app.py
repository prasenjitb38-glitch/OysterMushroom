import os
import tempfile
import unittest

import database


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        database.DB_FOLDER = cls.temp.name
        database.DB_FILE = os.path.join(cls.temp.name, "test.db")
        database.create_database()
        from modules.accounts import record_payment
        from modules.sales import SalesPage
        import services
        cls.record_payment, cls.SalesPage, cls.services = staticmethod(record_payment), SalesPage, services

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        with database.get_connection() as c:
            for table in ("customer_payments","supplier_payments","labour_payments","cash_ledger","sales","harvests","daily_production","purchases","expenses","labour","customers","suppliers","batches","stock_transactions"):
                c.execute(f"DELETE FROM {table}")
            c.execute("UPDATE settings SET value='0' WHERE key IN ('opening_mushroom_stock','expected_rate')")

    def seed(self):
        with database.get_connection() as c:
            c.execute("INSERT INTO batches(batch_no,production_date,bag_count,expected_yield) VALUES('B001','2026-09-04',100,40)")
            c.execute("INSERT INTO daily_production(production_date,batch_no,bags,production_kg,wastage_kg,saleable_kg) VALUES('2026-09-04','B001',100,12,.5,11.5)")
            c.execute("INSERT INTO harvests(harvest_date,batch_no,flush_no,quantity_kg,wastage_kg,grade) VALUES('2026-09-04','B001',1,10,1,'A')")
            customer=c.execute("INSERT INTO customers(name,opening_due) VALUES('Buyer',50)").lastrowid
            supplier=c.execute("INSERT INTO suppliers(name,opening_due) VALUES('Vendor',25)").lastrowid
            labour=c.execute("INSERT INTO labour(worker_name,work_date,batch_no,days,rate,amount,paid) VALUES('Worker','2026-09-04','B001',2,100,200,50)").lastrowid
            c.execute("INSERT INTO purchases(purchase_date,supplier_id,item,quantity,rate,total_amount,paid_amount,due_amount,batch_no) VALUES('2026-09-04',?,'Spawn',2,100,200,50,150,'B001')",(supplier,))
            return customer,supplier,labour

    def test_login(self):
        from modules.system_tools import authenticate
        self.assertTrue(authenticate("admin","admin"));self.assertFalse(authenticate("admin","bad"))

    def test_stock_sale_and_no_double_wastage(self):
        self.seed();self.assertEqual(self.services.mushroom_stock(),9)
        with self.assertRaises(OverflowError):self.SalesPage.validate_sale(10,100,0,0,9)
        with self.assertRaises(ValueError):self.SalesPage.validate_sale(1,100,0,101,9)
        with database.get_connection() as c:c.execute("INSERT INTO sales(invoice_no,sale_date,quantity_kg,rate_per_kg,total_amount,paid_amount) VALUES('T-1','2026-09-04',3,100,300,100)")
        self.assertEqual(self.services.mushroom_stock(),6)

    def test_due_payments_and_ledger(self):
        customer,supplier,labour=self.seed()
        with database.get_connection() as c:c.execute("INSERT INTO sales(invoice_no,sale_date,customer_id,quantity_kg,rate_per_kg,total_amount,paid_amount) VALUES('T-2','2026-09-04',?,1,100,100,20)",(customer,))
        self.assertEqual(self.services.customer_outstanding(customer),130)
        ledger_id=self.record_payment("2026-09-04","CUSTOMER PAYMENT",customer,30,"Cash","R1")
        self.record_payment("2026-09-04","SUPPLIER PAYMENT",supplier,20,"Bank","R2")
        self.record_payment("2026-09-04","LABOUR PAYMENT",labour,10,"Cash","R3")
        self.assertEqual(self.services.customer_outstanding(customer),100)
        self.assertEqual(self.services.supplier_outstanding(supplier),155)
        self.assertEqual(self.services.labour_due(),140)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger").fetchone()[0],3)
        from modules.accounts import update_payment,delete_payment
        update_payment(ledger_id,"2026-09-04","CUSTOMER PAYMENT",customer,20,"Cash","R1")
        self.assertEqual(self.services.customer_outstanding(customer),110)
        delete_payment(ledger_id);self.assertEqual(self.services.customer_outstanding(customer),130)

    def test_cash_and_raw_material_stock(self):
        from services import cash_balance,raw_material_stock
        with database.get_connection() as c:
            material=c.execute("SELECT id FROM raw_materials WHERE item='Spawn'").fetchone()[0]
            c.execute("UPDATE raw_materials SET opening_stock=5 WHERE id=?",(material,))
            c.execute("INSERT INTO purchases(purchase_date,item,quantity,rate,total_amount) VALUES('2026-09-04','Spawn',3,1,3)")
            c.execute("INSERT INTO material_usage(usage_date,material_id,quantity) VALUES('2026-09-04',?,2)",(material,))
            c.execute("INSERT INTO cash_ledger(transaction_date,transaction_type,payment_mode,debit,credit) VALUES('2026-09-04','Test','Cash',2,10)")
        self.assertEqual(raw_material_stock(material),6);self.assertEqual(cash_balance(),8)

    def test_batch_cost_and_pnl(self):
        self.seed()
        with database.get_connection() as c:
            c.execute("INSERT INTO expenses(expense_date,category,amount,batch_no) VALUES('2026-09-04','Electricity',50,'B001')")
            c.execute("INSERT INTO sales(invoice_no,sale_date,quantity_kg,rate_per_kg,total_amount,paid_amount) VALUES('T-3','2026-09-04',1,500,500,500)")
        row=self.services.batch_cost_rows()[0];self.assertEqual(row[6],450)
        result=self.services.pnl();self.assertEqual(result["cogs"],400);self.assertEqual(result["net"],50)

    def test_invoice_number(self):
        with database.get_connection() as c:c.execute("UPDATE settings SET value='BILL' WHERE key='invoice_prefix'")
        self.assertEqual(self.SalesPage.generate_invoice_no(),"BILL-00001")

    def test_gui_pages(self):
        try:
            import tkinter as tk, main
            root=tk.Tk();root.withdraw();app=main.MushroomApp(root)
            for name in ("production","harvest","stock","sales","expenses","customers","suppliers","labour","purchases","raw_materials","payments","ledger","batch_cost","profit_loss","reports","charts","backup_restore","settings","users"):
                getattr(app,name)();root.update_idletasks()
            root.destroy()
        except tk.TclError as e:self.skipTest(str(e))


if __name__ == "__main__": unittest.main(verbosity=2)
