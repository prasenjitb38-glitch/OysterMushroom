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
        from payment_service import record_payment
        from modules.sales import SalesPage
        import services
        cls.record_payment, cls.SalesPage, cls.services = staticmethod(record_payment), SalesPage, services

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        with database.get_connection() as c:
            for table in ("customer_payments","supplier_payments","labour_payments","cash_ledger","owner_capital","sales","harvests","daily_production","purchases","expenses","labour","material_usage","material_adjustments","customers","suppliers","batches","stock_transactions"):
                c.execute(f"DELETE FROM {table}")
            c.execute("UPDATE settings SET value='0' WHERE key IN ('opening_mushroom_stock','expected_rate','opening_cash','opening_bank')")
            c.execute("UPDATE raw_materials SET opening_stock=0,reorder_level=0")

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

    def test_account_openings_and_payment_directions(self):
        customer,supplier,labour=self.seed()
        with database.get_connection() as c:c.execute("UPDATE settings SET value='100' WHERE key='opening_cash'");c.execute("UPDATE settings SET value='200' WHERE key='opening_bank'")
        self.record_payment("2026-09-04","CUSTOMER PAYMENT",customer,30,"Cash")
        self.record_payment("2026-09-04","SUPPLIER PAYMENT",supplier,20,"Bank")
        self.record_payment("2026-09-04","LABOUR PAYMENT",labour,10,"Cash")
        self.assertEqual(self.services.cash_balance("Cash"),120)
        self.assertEqual(self.services.cash_balance("Bank"),180)
        self.assertEqual(self.services.cash_balance(),300)

    def test_date_filtered_pnl(self):
        self.seed()
        with database.get_connection() as c:
            c.execute("INSERT INTO sales(invoice_no,sale_date,quantity_kg,rate_per_kg,total_amount) VALUES('D1','2026-09-04',1,500,500)")
            c.execute("INSERT INTO purchases(purchase_date,item,quantity,rate,total_amount,batch_no) VALUES('2025-01-01','Old',1,900,900,'B001')")
            c.execute("INSERT INTO labour(worker_name,work_date,batch_no,amount) VALUES('Old','2025-01-01','B001',800)")
        result=self.services.pnl("2026-09-04","2026-09-04")
        self.assertEqual(result["sales"],500);self.assertEqual(result["cogs"],400)

    def test_sale_ledger_edit_delete_and_exact_batch(self):
        with database.get_connection() as c:
            b1=c.execute("INSERT INTO batches(batch_no,production_date) VALUES('B01','2026-09-04')").lastrowid
            b2=c.execute("INSERT INTO batches(batch_no,production_date) VALUES('B010','2026-09-04')").lastrowid
            c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg) VALUES('2026-09-04','B01',?,10)",(b1,));c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg) VALUES('2026-09-04','B010',?,10)",(b2,))
        sid=self.services.save_sale({"invoice_no":"S1","sale_date":"2026-09-04","batch_id":b1,"quantity_kg":3,"rate_per_kg":100,"paid_amount":100,"payment_mode":"Cash","notes":"B010 text"})
        self.assertEqual(self.services.mushroom_stock(),17)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='sales' AND source_id=?",(sid,)).fetchone()[0],1)
        self.services.save_sale({"invoice_no":"S1","sale_date":"2026-09-04","batch_id":b1,"quantity_kg":4,"rate_per_kg":100,"paid_amount":200,"payment_mode":"Cash"},sid)
        self.assertEqual(self.services.mushroom_stock(),16)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='sales' AND source_id=?",(sid,)).fetchone()[0],1)
        self.services.delete_sale(sid);self.assertEqual(self.services.mushroom_stock(),20)

    def test_raw_material_usage_adjustment_and_purchase(self):
        with database.get_connection() as c:mid=c.execute("SELECT id FROM raw_materials WHERE item='Spawn'").fetchone()[0]
        pid=self.services.save_purchase({"purchase_date":"2026-09-04","material_id":mid,"quantity":10,"rate":10,"paid_amount":50,"payment_mode":"Cash"})
        self.assertEqual(self.services.raw_material_stock(mid),10)
        self.services.save_purchase({"purchase_date":"2026-09-04","material_id":mid,"quantity":8,"rate":10,"paid_amount":0,"payment_mode":"Credit"},pid);self.assertEqual(self.services.raw_material_stock(mid),8)
        uid=self.services.save_material_usage({"usage_date":"2026-09-04","material_id":mid,"quantity":3});self.assertEqual(self.services.raw_material_stock(mid),5)
        self.services.save_material_usage({"usage_date":"2026-09-04","material_id":mid,"quantity":2},uid);self.assertEqual(self.services.raw_material_stock(mid),6)
        self.services.delete_material_usage(uid);self.assertEqual(self.services.raw_material_stock(mid),8)
        with self.assertRaises(OverflowError):self.services.save_material_adjustment({"adjustment_date":"2026-09-04","material_id":mid,"adjustment_type":"OUT","quantity":9})
        self.services.delete_source_record("purchases",pid);self.assertEqual(self.services.raw_material_stock(mid),0)

    def test_permissions_password_and_last_admin(self):
        self.assertTrue(self.services.require_permission("MANAGER","sales"))
        with self.assertRaises(PermissionError):self.services.require_permission("MANAGER","users")
        with self.assertRaises(PermissionError):self.services.require_permission("STAFF","sales.delete")
        with self.assertRaises(ValueError):database.validate_password("")
        with database.get_connection() as c:admin=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
        with self.assertRaises(ValueError):database.set_user_active(admin,False)

    def test_source_linked_ledger_is_protected(self):
        customer,_,_=self.seed();ledger=self.record_payment("2026-09-04","CUSTOMER PAYMENT",customer,10,"Cash")
        with self.assertRaises(PermissionError):self.services.delete_manual_ledger(ledger)

    def test_all_immediate_transactions_post_once(self):
        with database.get_connection() as c:
            mid=c.execute("SELECT id FROM raw_materials WHERE item='Spawn'").fetchone()[0]
            bid=c.execute("INSERT INTO batches(batch_no,production_date) VALUES('CASH','2026-09-04')").lastrowid
            c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg) VALUES('2026-09-04','CASH',?,5)",(bid,))
        self.services.save_expense({"expense_date":"2026-09-04","category":"Power","amount":20,"payment_mode":"Cash"})
        self.services.save_purchase({"purchase_date":"2026-09-04","material_id":mid,"quantity":2,"rate":10,"paid_amount":10,"payment_mode":"Cash"})
        self.services.save_labour({"worker_name":"W","work_date":"2026-09-04","days":1,"hours":0,"rate":10,"paid":5,"payment_mode":"Cash"})
        self.services.save_sale({"invoice_no":"CASH-1","sale_date":"2026-09-04","batch_id":bid,"quantity_kg":1,"rate_per_kg":100,"paid_amount":50,"payment_mode":"Cash"})
        self.assertEqual(self.services.cash_balance("Cash"),15)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger").fetchone()[0],4)

    def test_web_csrf_and_throttle(self):
        import web_app
        client=web_app.app.test_client()
        self.assertEqual(client.post("/login",data={"username":"x","password":"x"}).status_code,400)
        with client.session_transaction() as s:s["csrf_token"]="token"
        codes=[client.post("/login",data={"csrf_token":"token","username":"locked","password":"bad"}).status_code for _ in range(6)]
        self.assertEqual(codes[-1],429)

    def test_csrf_survives_forced_password_change_and_protects_supplier_form(self):
        import re
        import web_app

        def token(response):
            match=re.search(r'name="csrf_token"\s+value="([^"]+)"',response.get_data(as_text=True))
            self.assertIsNotNone(match)
            return match.group(1)

        with database.get_connection() as c:
            admin=c.execute("SELECT id,password_hash,must_change_password FROM users WHERE username='admin'").fetchone()
            c.execute("UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?",(database.hash_password("admin"),admin[0]))
        try:
            client=web_app.app.test_client()
            login_token=token(client.get("/login"))
            login=client.post("/login",data={"csrf_token":login_token,"username":"admin","password":"admin"})
            self.assertEqual((login.status_code,login.headers["Location"]), (302,"/change-password"))

            password_token=token(client.get("/change-password"))
            changed=client.post("/change-password",data={"csrf_token":password_token,"current_password":"admin","new_password":"admin123"})
            self.assertEqual((changed.status_code,changed.headers["Location"]), (302,"/"))

            form_token=token(client.get("/manage/supplier/new"))
            supplier={"name":"CSRF Flow Supplier","mobile":"9000000001","email":"csrf@example.test","address":"Test","opening_due":"0","notes":""}
            self.assertEqual(client.post("/manage/supplier/new",data=supplier).status_code,400)
            self.assertEqual(client.post("/manage/supplier/new",data={**supplier,"csrf_token":"CSRF Flow Supplier"}).status_code,400)
            saved=client.post("/manage/supplier/new",data={**supplier,"csrf_token":form_token})
            self.assertEqual((saved.status_code,saved.headers["Location"]),(302,"/suppliers"))
            with database.get_connection() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM suppliers WHERE name='CSRF Flow Supplier'").fetchone()[0],1)
                c.execute("DELETE FROM suppliers WHERE name='CSRF Flow Supplier'")
        finally:
            with database.get_connection() as c:
                c.execute("UPDATE users SET password_hash=?,must_change_password=? WHERE id=?",(admin[1],admin[2],admin[0]))

    def test_production_edit_delete_never_changes_stock_and_yield(self):
        with database.get_connection() as c:bid=c.execute("INSERT INTO batches(batch_no,production_date,bag_count,expected_yield) VALUES('P1','2026-09-01',10,20)").lastrowid;c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg,wastage_kg) VALUES('2026-09-02','P1',?,11,1)",(bid,))
        before=self.services.mushroom_stock();pid=self.services.save_production({"production_date":"2026-09-02","batch_id":bid,"bags":10,"production_kg":8,"wastage_kg":1})
        self.services.save_production({"production_date":"2026-09-03","batch_id":bid,"bags":10,"production_kg":12,"wastage_kg":2},pid);self.assertEqual(self.services.mushroom_stock(),before)
        self.services.delete_production(pid);self.assertEqual(self.services.mushroom_stock(),before);self.assertEqual(self.services.batch_summary(bid)["yield_pct"],50)
        with self.assertRaises(ValueError):self.services.delete_batch(bid)

    def test_party_statements_and_invoice_data(self):
        customer,supplier,_=self.seed()
        with database.get_connection() as c:
            bid=c.execute("SELECT id FROM batches WHERE batch_no='B001'").fetchone()[0]
            sid=c.execute("INSERT INTO sales(invoice_no,sale_date,customer_id,batch_id,batch_no,quantity_kg,rate_per_kg,total_amount,paid_amount,payment_mode) VALUES('ST1','2026-09-04',?,?,?,?,100,100,20,'Cash')",(customer,bid,'B001',1)).lastrowid
        self.record_payment("2026-09-05","CUSTOMER PAYMENT",customer,30,"Cash","RC1");self.record_payment("2026-09-05","SUPPLIER PAYMENT",supplier,20,"Cash","SP1")
        opening,rows=self.services.customer_statement(customer);self.assertEqual(opening,50);self.assertEqual(rows[-1][-1],100)
        opening,rows=self.services.supplier_statement(supplier);self.assertEqual(opening,25);self.assertEqual(rows[-1][-1],155)
        inv=self.services.invoice_data(sid);self.assertEqual(inv["batch"],"B001");self.assertIn("business_name",inv)

    def test_low_stock_warning(self):
        with database.get_connection() as c:mid=c.execute("SELECT id FROM raw_materials WHERE item='Spawn'").fetchone()[0];c.execute("UPDATE raw_materials SET opening_stock=2,reorder_level=3 WHERE id=?",(mid,))
        self.assertIn(mid,[r[0] for r in self.services.low_stock_materials()])

    def test_change_and_admin_reset_password(self):
        with database.get_connection() as c:admin=c.execute("SELECT id FROM users WHERE username='admin'").fetchone()[0];uid=c.execute("INSERT INTO users(username,password_hash,role,active) VALUES('staff1',?,'STAFF',1)",(database.hash_password('initial88'),)).lastrowid
        database.admin_reset_password(admin,uid,"temporary88")
        row=database.authenticate("staff1","temporary88");self.assertTrue(row[5])
        database.change_password(uid,"temporary88","changed888");row=database.authenticate("staff1","changed888");self.assertFalse(row[5])
        with self.assertRaises(PermissionError):database.admin_reset_password(uid,admin,"blocked888")

    def test_desktop_action_permissions(self):
        self.services.set_desktop_role("STAFF")
        try:
            with self.assertRaises(PermissionError):self.services.delete_production(1)
            with self.assertRaises(PermissionError):self.services.save_expense({"expense_date":"2026-09-04","category":"X","amount":1})
            self.assertTrue(self.services.require_permission("STAFF","production.create"))
            self.services.set_desktop_role("MANAGER")
            with self.assertRaises(PermissionError):self.services.enforce_desktop("users")
            self.assertTrue(self.services.enforce_desktop("sales.delete"))
        finally:self.services.set_desktop_role("ADMIN")

    def test_pdf_and_chart_execution(self):
        from invoice_pdf import generate_invoice_pdf_file
        from modules.analytics import generate_chart_file
        customer,_,_=self.seed()
        with database.get_connection() as c:bid=c.execute("SELECT id FROM batches WHERE batch_no='B001'").fetchone()[0];sid=c.execute("INSERT INTO sales(invoice_no,sale_date,customer_id,batch_id,batch_no,quantity_kg,rate_per_kg,total_amount) VALUES('PDF1','2026-09-04',?,?,?,?,100,100)",(customer,bid,'B001',1)).lastrowid
        pdf=os.path.join(self.temp.name,"invoice.pdf");png=os.path.join(self.temp.name,"chart.png");generate_invoice_pdf_file(sid,pdf);generate_chart_file(png)
        self.assertGreater(os.path.getsize(pdf),500);self.assertGreater(os.path.getsize(png),500)

    def test_realistic_end_to_end_business(self):
        from modules.accounts import record_payment
        with database.get_connection() as c:
            supplier=c.execute("INSERT INTO suppliers(name) VALUES('Farm Supplier')").lastrowid;customer=c.execute("INSERT INTO customers(name) VALUES('Hotel Buyer')").lastrowid
            mids={n:c.execute("SELECT id FROM raw_materials WHERE item=?",(n,)).fetchone()[0] for n in ('Paddy Straw','Spawn','Polybag')}
        self.services.save_purchase({"purchase_date":"2026-09-01","supplier_id":supplier,"material_id":mids['Paddy Straw'],"quantity":100,"rate":5,"paid_amount":300,"payment_mode":"Cash"})
        self.services.save_purchase({"purchase_date":"2026-09-01","supplier_id":supplier,"material_id":mids['Spawn'],"quantity":50,"rate":10,"paid_amount":200,"payment_mode":"Cash"})
        self.services.save_purchase({"purchase_date":"2026-09-01","supplier_id":supplier,"material_id":mids['Polybag'],"quantity":100,"rate":1,"paid_amount":100,"payment_mode":"Cash"})
        bid=self.services.save_batch({"batch_no":"B001","production_date":"2026-09-02","bag_count":100,"expected_yield":50})
        for material,qty in ((mids['Paddy Straw'],50),(mids['Spawn'],10),(mids['Polybag'],100)):self.services.save_material_usage({"usage_date":"2026-09-02","material_id":material,"batch_id":bid,"quantity":qty})
        self.services.save_labour({"worker_name":"Worker","work_date":"2026-09-02","batch_no":"B001","days":10,"rate":100,"paid":200,"payment_mode":"Cash"})
        self.services.save_expense({"expense_date":"2026-09-02","category":"Electricity","amount":300,"payment_mode":"Cash","batch_no":"B001"})
        self.services.save_production({"production_date":"2026-09-03","batch_id":bid,"bags":100,"production_kg":50,"wastage_kg":0});self.assertEqual(self.services.mushroom_stock(),0)
        with database.get_connection() as c:c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg,wastage_kg) VALUES('2026-09-04','B001',?,50,5)",(bid,))
        self.assertEqual(self.services.mushroom_stock(),45)
        sale=self.services.save_sale({"invoice_no":"E2E1","sale_date":"2026-09-04","customer_id":customer,"batch_id":bid,"quantity_kg":20,"rate_per_kg":100,"paid_amount":800,"payment_mode":"Cash"});self.assertEqual(self.services.mushroom_stock(),25);self.assertEqual(self.services.customer_outstanding(customer),1200)
        record_payment("2026-09-05","CUSTOMER PAYMENT",customer,500,"Cash");record_payment("2026-09-05","SUPPLIER PAYMENT",supplier,100,"Cash")
        with database.get_connection() as c:labour=c.execute("SELECT id FROM labour WHERE worker_name='Worker'").fetchone()[0]
        record_payment("2026-09-05","LABOUR PAYMENT",labour,100,"Cash")
        self.assertEqual(self.services.customer_outstanding(customer),700);self.assertEqual(self.services.supplier_outstanding(supplier),400);self.assertEqual(self.services.labour_due(),700);self.assertEqual(self.services.cash_balance('Cash'),0)
        costs=self.services.batch_cost_rows()[0];self.assertEqual(costs[6],1750);self.assertEqual(costs[8],35)
        result=self.services.pnl();self.assertEqual(result['gross'],550);self.assertEqual(result['net'],250);self.assertEqual(result['margin'],12.5)
        self.services.save_sale({"invoice_no":"E2E1","sale_date":"2026-09-04","customer_id":customer,"batch_id":bid,"quantity_kg":15,"rate_per_kg":100,"paid_amount":600,"payment_mode":"Cash"},sale);self.assertEqual(self.services.mushroom_stock(),30)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='sales' AND source_id=?",(sale,)).fetchone()[0],1)
        self.services.delete_sale(sale);self.assertEqual(self.services.mushroom_stock(),45)

    def test_backup_restore_roundtrip(self):
        import shutil,sqlite3
        from backup_service import backup_database,restore_database
        working=os.path.join(self.temp.name,"working.db");backup=os.path.join(self.temp.name,"backup.db");shutil.copy2(database.DB_FILE,working);backup_database(working,backup)
        with sqlite3.connect(working) as c:c.execute("INSERT INTO settings(key,value) VALUES('roundtrip','changed') ON CONFLICT(key) DO UPDATE SET value='changed'")
        restore_database(backup,working)
        with sqlite3.connect(working) as c:self.assertIsNone(c.execute("SELECT value FROM settings WHERE key='roundtrip'").fetchone());self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0],"ok");self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_dashboard_event_callback(self):
        from events import subscribe,unsubscribe,publish
        seen=[]
        def callback(event):seen.append(event)
        subscribe(callback);publish("sale_changed");unsubscribe(callback);self.assertEqual(seen,["sale_changed"])

    def test_failing_event_subscriber_cannot_misreport_committed_payment(self):
        from events import subscribe,unsubscribe
        customer,_,_=self.seed()
        def broken(_event):raise RuntimeError("UI refresh failed")
        subscribe(broken)
        try:ledger=self.record_payment("2026-09-06","CUSTOMER PAYMENT",customer,10,"Bank","EVENT-R1")
        finally:unsubscribe(broken)
        self.assertIsNotNone(ledger);self.assertEqual(self.services.customer_outstanding(customer),40)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE reference='EVENT-R1'").fetchone()[0],1)

    def test_edit_delete_reversal_stress(self):
        from modules.accounts import record_payment,update_payment,delete_payment
        customer,supplier,labour=self.seed()
        with database.get_connection() as c:bid=c.execute("SELECT id FROM batches WHERE batch_no='B001'").fetchone()[0];hid=c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg,wastage_kg) VALUES('2026-09-04','B001',?,10,1)",(bid,)).lastrowid
        self.assertEqual(self.services.mushroom_stock(),18)
        with database.get_connection() as c:c.execute("UPDATE harvests SET quantity_kg=12,wastage_kg=2 WHERE id=?",(hid,))
        self.assertEqual(self.services.mushroom_stock(),19)
        with database.get_connection() as c:c.execute("DELETE FROM harvests WHERE id=?",(hid,))
        self.assertEqual(self.services.mushroom_stock(),9)
        eid=self.services.save_expense({"expense_date":"2026-09-04","category":"Test","amount":100,"payment_mode":"Bank"});self.assertEqual(self.services.cash_balance("Bank"),-100)
        self.services.save_expense({"expense_date":"2026-09-04","category":"Test","amount":60,"payment_mode":"Bank"},eid);self.assertEqual(self.services.cash_balance("Bank"),-60);self.services.delete_source_record("expenses",eid);self.assertEqual(self.services.cash_balance("Bank"),0)
        aid=self.services.save_material_adjustment({"adjustment_date":"2026-09-04","material_id":self._material('Spawn'),"adjustment_type":"IN","quantity":5});self.services.save_material_adjustment({"adjustment_date":"2026-09-04","material_id":self._material('Spawn'),"adjustment_type":"IN","quantity":3},aid);self.assertEqual(self.services.raw_material_stock(self._material('Spawn')),5);self.services.delete_material_adjustment(aid);self.assertEqual(self.services.raw_material_stock(self._material('Spawn')),2)
        lid=record_payment("2026-09-04","CUSTOMER PAYMENT",customer,10,"Cash");update_payment(lid,"2026-09-04","CUSTOMER PAYMENT",customer,5,"Cash");delete_payment(lid)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger GROUP BY source_table,source_id HAVING COUNT(*)>1").fetchall(),[])

    def test_web_production_routes_and_roles(self):
        import web_app
        client=web_app.app.test_client()
        def role(name,must=False):
            with client.session_transaction() as s:s["user"]={"id":1,"name":name,"role":name,"must_change_password":must};s["csrf_token"]="secure-token"
        role("STAFF");self.assertEqual(client.get("/api/reports").status_code,403);self.assertEqual(client.get("/backup/download").status_code,403)
        role("MANAGER");self.assertEqual(client.get("/api/reports").status_code,200);self.assertEqual(client.get("/backup/download").status_code,403)
        role("ADMIN",True);response=client.get("/");self.assertEqual(response.status_code,302);self.assertIn("change-password",response.location)
        role("ADMIN");self.assertEqual(client.get("/api/reports").status_code,200);self.assertEqual(client.get("/charts.png").status_code,200);self.assertEqual(client.get("/backup/download").status_code,200)

    def test_complete_role_aware_web_navigation(self):
        import web_app
        client=web_app.app.test_client()
        expected={
            "ADMIN":{item[1] for item in web_app.NAV_ITEMS},
            "MANAGER":{"dashboard","production","harvest","stock","sales","raw_materials_web","purchases_web","expenses_web","customers_web","suppliers_web","labour_web","payments_web","ledger_web","capital_web","batch_cost_web","pnl_web","reports_web","charts_web","invoices_web"},
            "STAFF":{"dashboard","production","harvest","stock","sales","customers_web","invoices_web"},
        }
        rules={rule.endpoint:rule.rule for rule in web_app.app.url_map.iter_rules() if "<" not in rule.rule}
        for role,endpoints in expected.items():
            with client.session_transaction() as s:s["user"]={"id":1,"name":role,"role":role,"must_change_password":False};s["csrf_token"]="secure-token"
            page=client.get("/")
            self.assertEqual(page.status_code,200)
            html=page.get_data(as_text=True)
            for label,endpoint,action in web_app.NAV_ITEMS:
                displayed=f'href="{rules[endpoint]}"' in html
                self.assertEqual(displayed,endpoint in endpoints,(role,endpoint))
                if endpoint in endpoints:self.assertEqual(client.get(rules[endpoint]).status_code,200,(role,endpoint))
            self.assertIn('id="nav-toggle"',html);self.assertIn('aria-controls="sidebar"',html);self.assertIn("navigation.js",html)
        css=client.get("/static/mobile.css").get_data(as_text=True);js=client.get("/static/navigation.js").get_data(as_text=True)
        self.assertIn("nav-collapsed",css);self.assertIn("nav-open",css);self.assertIn("addEventListener('click'",js)

    def test_web_health_endpoint(self):
        import web_app
        response=web_app.app.test_client().get("/health")
        self.assertEqual(response.status_code,200);self.assertEqual(response.json["integrity"],"ok")
        self.assertEqual(response.json["database_file"],os.path.abspath(database.DB_FILE))
        self.assertTrue(response.json["directory_exists"]);self.assertTrue(response.json["database_exists"])
        self.assertEqual(response.json["persistent_database"],response.json["path_under_var_data"] and response.json["persistent_disk_mounted"])

    def test_database_path_resolution_by_environment(self):
        production_dir,production_file=database.resolve_database_paths({"APP_ENV":"production"})
        self.assertEqual(production_dir,os.path.abspath("/var/data"));self.assertEqual(production_file,os.path.join(production_dir,"mushroom.db"))
        configured_dir,configured_file=database.resolve_database_paths({"APP_ENV":"production","MUSHROOM_DATA_DIR":"/var/data"})
        self.assertEqual(configured_file,os.path.join(configured_dir,"mushroom.db"));self.assertTrue(configured_file.replace("\\","/").endswith("/var/data/mushroom.db"))
        local_dir,local_file=database.resolve_database_paths({},base_dir=os.path.join(self.temp.name,"project"))
        self.assertEqual(local_file,os.path.join(local_dir,"mushroom.db"));self.assertTrue(local_dir.endswith("database"));self.assertNotIn("/var/data",local_file.replace("\\","/"))

    def test_browser_post_crud_workflow_and_reversals(self):
        import web_app
        self.services.set_desktop_role("ADMIN")
        client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="web-token"
        def post(path,**data):
            data["csrf_token"]="web-token";response=client.post(path,data=data)
            self.assertEqual(response.status_code,302,(path,response.get_data(as_text=True)));return response
        post("/manage/supplier/new",name="Web Supplier",mobile="111",email="s@test",address="A",opening_due="25",notes="")
        post("/manage/customer/new",name="Web Customer",mobile="222",email="c@test",address="B",opening_due="50",notes="")
        with database.get_connection() as c:
            supplier=c.execute("SELECT id FROM suppliers WHERE name='Web Supplier'").fetchone()[0];customer=c.execute("SELECT id FROM customers WHERE name='Web Customer'").fetchone()[0];material=c.execute("SELECT id FROM raw_materials WHERE item='Spawn'").fetchone()[0]
        purchase={"purchase_date":"2026-09-05","purchase_invoice":"WEB-P1","supplier_id":str(supplier),"material_id":str(material),"batch_no":"","quantity":"5","unit":"Kg","rate":"10","paid_amount":"20","payment_mode":"Cash","notes":"web"}
        post("/manage/purchase/new",**purchase);self.assertEqual(self.services.raw_material_stock(material),5)
        with database.get_connection() as c:pid=c.execute("SELECT id FROM purchases WHERE purchase_invoice='WEB-P1'").fetchone()[0];self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='purchases' AND source_id=?",(pid,)).fetchone()[0],1)
        purchase["quantity"]="7";post(f"/manage/purchase/{pid}/edit",**purchase);self.assertEqual(self.services.raw_material_stock(material),7)
        post(f"/manage/purchase/{pid}/delete");self.assertEqual(self.services.raw_material_stock(material),0)
        batch={"batch_no":"WEB-B1","production_date":"2026-09-05","straw_qty":"10","spawn_qty":"1","bag_count":"20","expected_yield":"8","expected_harvest_date":"","status":"Growing","notes":""}
        post("/manage/batch/new",**batch)
        with database.get_connection() as c:bid=c.execute("SELECT id FROM batches WHERE batch_no='WEB-B1'").fetchone()[0]
        post("/manage/adjustment/new",adjustment_date="2026-09-05",material_id=str(material),batch_id="",adjustment_type="IN",quantity="3",notes="")
        post("/manage/usage/new",usage_date="2026-09-05",material_id=str(material),batch_id=str(bid),quantity="1",notes="")
        before=self.services.mushroom_stock();post("/manage/production/new",production_date="2026-09-05",batch_id=str(bid),bags="20",production_kg="8",wastage_kg=".5",notes="");self.assertEqual(self.services.mushroom_stock(),before)
        post("/manage/harvest/new",harvest_date="2026-09-05",batch_id=str(bid),flush_no="1",quantity_kg="10",wastage_kg="1",grade="A",notes="");self.assertEqual(self.services.mushroom_stock(),before+9)
        post("/manage/sale/new",sale_date="2026-09-05",customer_id=str(customer),batch_id=str(bid),quantity_kg="3",rate_per_kg="100",discount="0",paid_amount="100",payment_mode="Cash",notes="")
        self.assertEqual(self.services.mushroom_stock(),before+6)
        with database.get_connection() as c:sale_id=c.execute("SELECT id FROM sales WHERE customer_id=?",(customer,)).fetchone()[0]
        due_before=self.services.customer_outstanding(customer);cash_before=self.services.cash_balance("Cash")
        post("/manage/payment/new",payment_date="2026-09-05",party=f"CUSTOMER PAYMENT|{customer}",amount="20",payment_mode="Cash",reference="WEB-R1",notes="")
        self.assertEqual(self.services.customer_outstanding(customer),due_before-20);self.assertEqual(self.services.cash_balance("Cash"),cash_before+20)
        with database.get_connection() as c:payment_id=c.execute("SELECT id FROM cash_ledger WHERE reference='WEB-R1'").fetchone()[0]
        post(f"/manage/payment/{payment_id}/edit",payment_date="2026-09-05",party=f"CUSTOMER PAYMENT|{customer}",amount="10",payment_mode="Cash",reference="WEB-R1",notes="edited")
        self.assertEqual(self.services.customer_outstanding(customer),due_before-10);self.assertEqual(self.services.cash_balance("Cash"),cash_before+10)
        post("/manage/expense/new",expense_date="2026-09-05",category="Web",description="Test",amount="30",payment_mode="Cash",batch_no="",notes="")
        with database.get_connection() as c:eid=c.execute("SELECT id FROM expenses WHERE category='Web'").fetchone()[0]
        self.assertEqual(self.services.cash_balance("Cash"),cash_before-20)
        post(f"/manage/expense/{eid}/edit",expense_date="2026-09-05",category="Web",description="Edited",amount="10",payment_mode="Cash",batch_no="",notes="");self.assertEqual(self.services.cash_balance("Cash"),cash_before)
        post(f"/manage/expense/{eid}/delete");self.assertEqual(self.services.cash_balance("Cash"),cash_before+10)
        post(f"/manage/payment/{payment_id}/delete");self.assertEqual(self.services.customer_outstanding(customer),due_before);self.assertEqual(self.services.cash_balance("Cash"),cash_before)
        post(f"/manage/sale/{sale_id}/delete");self.assertEqual(self.services.mushroom_stock(),before+9)
        post("/manage/user/new",username="webstaff",full_name="Web Staff",password="Temporary88",role="STAFF")
        with database.get_connection() as c:user_id=c.execute("SELECT id FROM users WHERE username='webstaff'").fetchone()[0]
        post(f"/manage/user/{user_id}/reset",password="ChangedTemp99")
        self.assertTrue(database.authenticate("webstaff","ChangedTemp99")[5])
        post(f"/manage/user/{user_id}/toggle");self.assertIsNone(database.authenticate("webstaff","ChangedTemp99"))
        with client.session_transaction() as s:s["user"]={"id":2,"name":"Staff","role":"STAFF","must_change_password":False};s["csrf_token"]="web-token"
        self.assertEqual(client.get(f"/manage/supplier/{supplier}/edit").status_code,403);self.assertEqual(client.post(f"/manage/supplier/{supplier}/delete",data={"csrf_token":"web-token"}).status_code,403)

    def test_web_crud_controls_and_dropdowns(self):
        import web_app
        client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="web-token"
        expected=(("/suppliers","+ New Supplier"),("/customers","+ New Customer"),("/purchases","+ New Purchase"),("/expenses","+ New Expense"),("/labour","+ New Labour"),("/production","+ New Batch"),("/production","+ Daily Production"),("/harvest","+ New Harvest"),("/sales","+ New Sale"),("/stock","+ New Stock Adjustment"),("/raw-materials","+ New Material"),("/payments","+ New Payment"),("/users","+ New User"))
        for path,label in expected:self.assertIn(label,client.get(path).get_data(as_text=True),(path,label))
        purchase=client.get("/manage/purchase/new").get_data(as_text=True);self.assertIn('name="supplier_id"',purchase);self.assertIn('name="material_id"',purchase);self.assertNotIn("Supplier ID",purchase);self.assertIn("calculated-total",purchase)
        sale=client.get("/manage/sale/new").get_data(as_text=True);self.assertIn('name="customer_id"',sale);self.assertIn('name="batch_id"',sale)
        payment=client.get("/manage/payment/new").get_data(as_text=True);self.assertIn('name="party"',payment);self.assertNotIn("Party ID",payment)
        batch=client.get("/manage/batch/new").get_data(as_text=True);self.assertIn('name="straw_type"',batch);self.assertIn('name="bag_size"',batch);self.assertIn('name="room_rack"',batch)
        production=client.get("/manage/production/new").get_data(as_text=True);self.assertIn('name="room_rack"',production);self.assertEqual(client.get("/batch-cost").status_code,200)
        with client.session_transaction() as s:s["user"]={"id":2,"name":"Staff","role":"STAFF","must_change_password":False};s["csrf_token"]="web-token"
        self.assertNotIn("+ New Customer",client.get("/customers").get_data(as_text=True));self.assertEqual(client.get("/manage/purchase/new").status_code,403);self.assertEqual(client.get("/manage/user/new").status_code,403)

    def test_browser_purchase_other_material_creation_reuse_and_reversal(self):
        import web_app
        self.services.set_desktop_role("ADMIN");client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="other-token"
        with database.get_connection() as c:
            supplier=c.execute("INSERT INTO suppliers(name) VALUES('Cash')").lastrowid;other=c.execute("SELECT id FROM raw_materials WHERE LOWER(TRIM(item))='other'").fetchone()[0];polybag=c.execute("SELECT id FROM raw_materials WHERE item='Polybag'").fetchone()[0]
        def post(path,**data):data["csrf_token"]="other-token";response=client.post(path,data=data);self.assertEqual(response.status_code,302,(path,response.get_data(as_text=True)));return response
        def purchase(invoice,name,quantity,unit="Kg",material_id=None):post("/manage/purchase/new",purchase_date="2026-09-05",purchase_invoice=invoice,supplier_id=str(supplier),material_id=str(material_id or other),material_name=name,batch_no="",quantity=str(quantity),unit=unit,rate="5",paid_amount="0",payment_mode="Credit",notes="")
        form=client.get("/manage/purchase/new").get_data(as_text=True);self.assertIn("Material Name",form);self.assertIn("data-unit=",form);self.assertIn("n.required=other",form);self.assertIn('value="Pcs"',form);self.assertIn('value="Piece"',form)
        import re
        batch_select=re.search(r'<select name="batch_no"([^>]*)>',form);self.assertIsNotNone(batch_select);self.assertNotIn("required",batch_select.group(1))
        post("/manage/purchase/new",purchase_date="2026-09-05",purchase_invoice="FOGGER-1",supplier_id=str(supplier),material_id=str(other),material_name="Fogger Kit",batch_no="",quantity="1",unit="Piece",rate="3400",paid_amount="3400",payment_mode="Cash",notes="")
        with database.get_connection() as c:
            fogger=c.execute("SELECT id,item,unit FROM raw_materials WHERE item='Fogger Kit'").fetchone();fog_purchase=c.execute("SELECT id,total_amount,due_amount,unit FROM purchases WHERE purchase_invoice='FOGGER-1'").fetchone();self.assertEqual(fog_purchase[1:],(3400.0,0.0,"Piece"));self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='purchases' AND source_id=?",(fog_purchase[0],)).fetchone()[0],1)
        self.assertEqual(self.services.raw_material_stock(fogger[0]),1);self.assertEqual(self.services.cash_balance("Cash"),-3400)
        purchase("PCS-1","Plastic Clip",2,"Pcs")
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT unit FROM raw_materials WHERE item='Plastic Clip'").fetchone()[0],"Pcs")
        purchase("OTHER-1","Wood Dust",50)
        with database.get_connection() as c:
            rows=[r for r in c.execute("SELECT id,item,unit FROM raw_materials") if " ".join(r[1].split()).casefold()=="wood dust"];self.assertEqual(len(rows),1);material_id=rows[0][0];self.assertEqual(rows[0][2],"Kg");first=c.execute("SELECT id,item,unit FROM purchases WHERE purchase_invoice='OTHER-1'").fetchone();self.assertEqual((first[1],first[2]),("Wood Dust","Kg"))
        self.assertEqual(self.services.raw_material_stock(material_id),50)
        purchase("OTHER-2","  wood   dust  ",10,"Litre")
        with database.get_connection() as c:self.assertEqual(sum(1 for r in c.execute("SELECT item FROM raw_materials") if " ".join(r[0].split()).casefold()=="wood dust"),1);second=c.execute("SELECT id,material_id,unit FROM purchases WHERE purchase_invoice='OTHER-2'").fetchone();self.assertEqual((second[1],second[2]),(material_id,"Kg"))
        self.assertEqual(self.services.raw_material_stock(material_id),60)
        post(f"/manage/purchase/{first[0]}/edit",purchase_date="2026-09-05",purchase_invoice="OTHER-1",supplier_id=str(supplier),material_id=str(material_id),material_name="",batch_no="",quantity="70",unit="Litre",rate="5",paid_amount="0",payment_mode="Credit",notes="");self.assertEqual(self.services.raw_material_stock(material_id),80)
        post(f"/manage/purchase/{first[0]}/delete");self.assertEqual(self.services.raw_material_stock(material_id),10)
        post(f"/manage/purchase/{second[0]}/delete");self.assertEqual(self.services.raw_material_stock(material_id),0)
        purchase("UNIT-1","",5,"Kg",polybag)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT unit FROM purchases WHERE purchase_invoice='UNIT-1'").fetchone()[0],"Piece")

    def test_customer_credit_payment_can_be_reduced_after_sale_deleted(self):
        from modules.accounts import record_payment,update_payment
        self.services.set_desktop_role("ADMIN")
        with database.get_connection() as c:customer=c.execute("INSERT INTO customers(name) VALUES('Credit Customer')").lastrowid;c.execute("INSERT INTO batches(batch_no,production_date) VALUES('CREDIT-B','2026-09-05')");bid=c.execute("SELECT id FROM batches WHERE batch_no='CREDIT-B'").fetchone()[0];c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg,wastage_kg) VALUES('2026-09-05','CREDIT-B',?,10,0)",(bid,))
        sale=self.services.save_sale({"invoice_no":"CREDIT-1","sale_date":"2026-09-05","customer_id":customer,"batch_id":bid,"quantity_kg":5,"rate_per_kg":100,"discount":0,"paid_amount":0,"payment_mode":"Credit"})
        ledger=record_payment("2026-09-05","CUSTOMER PAYMENT",customer,500,"Bank","CREDIT-R")
        self.services.delete_sale(sale);self.assertEqual(self.services.customer_outstanding(customer),-500)
        import web_app
        client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="credit-token"
        response=client.post(f"/manage/payment/{ledger}/edit",data={"csrf_token":"credit-token","payment_date":"2026-09-05","party":f"CUSTOMER PAYMENT|{customer}","amount":"400","payment_mode":"Bank","reference":"CREDIT-R","notes":"reduced credit"})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.services.customer_outstanding(customer),-400)
        with self.assertRaises(ValueError):update_payment(ledger,"2026-09-05","CUSTOMER PAYMENT",customer,450,"Bank","CREDIT-R")

    def test_browser_supplier_and_labour_payment_edit_delete(self):
        import web_app
        self.services.set_desktop_role("ADMIN");customer,supplier,labour=self.seed();client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="pay-token"
        def post(path,**data):data["csrf_token"]="pay-token";response=client.post(path,data=data);self.assertEqual(response.status_code,302);return response
        with database.get_connection() as c:c.execute("INSERT INTO labour(worker_name,work_date,amount,paid) VALUES('Other Worker','2026-09-05',1000,0)")
        with self.assertRaises(ValueError):self.record_payment("2026-09-05","LABOUR PAYMENT",labour,151,"Bank","TOO-MUCH")
        cases=(("SUPPLIER PAYMENT",supplier,"SUP-WEB",100,self.services.supplier_outstanding),("LABOUR PAYMENT",labour,"LAB-WEB",100,lambda _id:self.services.labour_due()))
        for kind,party,reference,amount,due in cases:
            before=due(party);post("/manage/payment/new",payment_date="2026-09-05",party=f"{kind}|{party}",amount=str(amount),payment_mode="Bank",reference=reference,notes="")
            with database.get_connection() as c:ledger=c.execute("SELECT id FROM cash_ledger WHERE reference=?",(reference,)).fetchone()[0]
            self.assertEqual(due(party),before-amount);post(f"/manage/payment/{ledger}/edit",payment_date="2026-09-05",party=f"{kind}|{party}",amount="50",payment_mode="Bank",reference=reference,notes="edited");self.assertEqual(due(party),before-50)
            with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE id=?",(ledger,)).fetchone()[0],1)
            post(f"/manage/payment/{ledger}/delete");self.assertEqual(due(party),before)
        labour_page=client.get("/labour").get_data(as_text=True)
        self.assertIn("<td>150.0</td>",labour_page)

    def test_payment_edit_uses_party_id_and_credit_update_rolls_back(self):
        from payment_service import record_payment,update_payment
        from web_crud import definition,existing
        self.services.set_desktop_role("ADMIN")
        with database.get_connection() as c:
            c.execute("INSERT INTO customers(name,opening_due) VALUES('Offset Customer',1)")
            customer=c.execute("INSERT INTO customers(name,opening_due) VALUES('Actual Customer',100)").lastrowid
        ledger=record_payment("2026-09-06","CUSTOMER PAYMENT",customer,25,"Bank","PARTY-ID")
        values=existing("payment",ledger,definition("payment"))
        self.assertEqual(values["party"],f"CUSTOMER PAYMENT|{customer}")
        with self.assertRaises(ValueError):
            update_payment(ledger,"2026-09-06","CUSTOMER PAYMENT",customer,20,"Credit","PARTY-ID")
        self.assertEqual(self.services.customer_outstanding(customer),75)
        with database.get_connection() as c:
            self.assertEqual(c.execute("SELECT amount,payment_mode FROM customer_payments WHERE customer_id=?",(customer,)).fetchone(),(25.0,"Bank"))
            self.assertEqual(c.execute("SELECT credit,payment_mode FROM cash_ledger WHERE id=?",(ledger,)).fetchone(),(25.0,"Bank"))

    def test_desktop_manual_payment_types_remain_supported(self):
        from payment_service import delete_payment,record_payment,update_payment
        self.services.set_desktop_role("ADMIN")
        ledger=record_payment("2026-09-06","OTHER INCOME",None,40,"Cash","OTHER-I")
        second=record_payment("2026-09-06","OTHER INCOME",None,10,"Cash","OTHER-I-2")
        self.assertEqual(self.services.cash_balance("Cash"),50)
        update_payment(ledger,"2026-09-06","OTHER PAYMENT",None,15,"Cash","OTHER-O")
        self.assertEqual(self.services.cash_balance("Cash"),-5)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='manual_payment'").fetchone()[0],2)
        delete_payment(ledger)
        self.assertEqual(self.services.cash_balance("Cash"),10)
        delete_payment(second)
        self.assertEqual(self.services.cash_balance("Cash"),0)

    def test_customer_receipt_is_atomic_and_reference_is_per_party(self):
        import sqlite3
        from unittest import mock
        import payment_service
        self.services.set_desktop_role("ADMIN")
        customer,_,_=self.seed()
        with database.get_connection() as c:other=c.execute("INSERT INTO customers(name,opening_due) VALUES('Other Customer',100)").lastrowid
        self.record_payment("2026-09-06","CUSTOMER PAYMENT",customer,10,"Bank","Receipt-1")
        with self.assertRaises(ValueError):self.record_payment("2026-09-06","CUSTOMER PAYMENT",customer,5,"Bank"," receipt-1 ")
        self.record_payment("2026-09-06","CUSTOMER PAYMENT",other,5,"Bank","receipt-1")
        with mock.patch.object(payment_service,"post_ledger",side_effect=sqlite3.IntegrityError("ledger failed")):
            with self.assertRaises(sqlite3.IntegrityError):self.record_payment("2026-09-06","CUSTOMER PAYMENT",customer,5,"Bank","ROLLBACK")
        with database.get_connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM customer_payments WHERE reference_no='ROLLBACK'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE reference='ROLLBACK'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM customer_payments WHERE LOWER(reference_no)='receipt-1'").fetchone()[0],2)

    def test_live_payment_and_invoice_pdf_regression(self):
        import web_app
        self.services.set_desktop_role("ADMIN");client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="live-regression"
        with database.get_connection() as c:
            customer=c.execute("INSERT INTO customers(name,mobile,address,opening_due) VALUES('DEMO CUSTOMER','9999999999','West Bengal',1000)").lastrowid
            batch=c.execute("INSERT INTO batches(batch_no,production_date) VALUES('LIVE-PDF','2026-09-06')").lastrowid
            c.execute("INSERT INTO harvests(harvest_date,batch_no,batch_id,quantity_kg,wastage_kg) VALUES('2026-09-06','LIVE-PDF',?,10,0)",(batch,))
        sale=self.services.save_sale({"invoice_no":"INV-LIVE-1","sale_date":"2026-09-06","customer_id":customer,"batch_id":batch,"quantity_kg":5,"rate_per_kg":400,"discount":0,"paid_amount":800,"payment_mode":"Cash"})
        due_before=self.services.customer_outstanding(customer);bank_before=self.services.cash_balance("Bank")
        receipt={"csrf_token":"live-regression","payment_date":"2026-09-06","party":f"CUSTOMER PAYMENT|{customer}","amount":"500","payment_mode":"Bank","reference":"DEMO-RCPT-001","notes":""}
        response=client.post("/manage/payment/new",data=receipt)
        self.assertEqual(response.status_code,302);self.assertEqual(self.services.customer_outstanding(customer),due_before-500);self.assertEqual(self.services.cash_balance("Bank"),bank_before+500)
        duplicate=client.post("/manage/payment/new",data=receipt)
        self.assertNotEqual(duplicate.status_code,500);self.assertEqual(self.services.customer_outstanding(customer),due_before-500)
        partial=dict(receipt,reference="DEMO-PARTIAL",payment_mode="Credit")
        failed=client.post("/manage/payment/new",data=partial)
        self.assertNotEqual(failed.status_code,500);self.assertEqual(self.services.customer_outstanding(customer),due_before-500)
        pdf=client.get(f"/invoice/{sale}.pdf");self.assertEqual(pdf.status_code,200);self.assertEqual(pdf.mimetype,"application/pdf");self.assertTrue(pdf.data.startswith(b"%PDF"));self.assertGreater(len(pdf.data),500)
        from unittest import mock
        with mock.patch("web_app.generate_invoice_pdf_file",side_effect=TypeError("broken PDF data")):
            unavailable=client.get(f"/invoice/{sale}.pdf")
        self.assertEqual(unavailable.status_code,503)
        with database.get_connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM customer_payments WHERE reference_no='DEMO-RCPT-001'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='customer_payments' AND reference='DEMO-RCPT-001'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM customer_payments WHERE reference_no='DEMO-PARTIAL'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE reference='DEMO-PARTIAL'").fetchone()[0],0)

    def test_web_runtime_imports_do_not_require_tkinter(self):
        import subprocess,sys
        script="""import builtins
real_import=builtins.__import__
def no_tk(name,*args,**kwargs):
    if name=='tkinter' or name.startswith('tkinter.'):
        raise ImportError('tkinter is unavailable on Render')
    return real_import(name,*args,**kwargs)
builtins.__import__=no_tk
import web_app
from invoice_pdf import generate_invoice_pdf_file
from payment_service import record_payment
print('web-safe')
"""
        env=os.environ.copy();env["MUSHROOM_DATA_DIR"]=self.temp.name
        result=subprocess.run([sys.executable,"-c",script],cwd=os.path.dirname(__file__),env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn("web-safe",result.stdout)

    def test_split_purchase_cash_bank_and_ledger_summary(self):
        import web_app
        self.services.set_desktop_role("ADMIN");client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="split-token"
        with database.get_connection() as c:
            supplier=c.execute("INSERT INTO suppliers(name) VALUES('Split Cash')").lastrowid
            other=c.execute("SELECT id FROM raw_materials WHERE LOWER(TRIM(item))='other'").fetchone()[0]
            c.execute("DELETE FROM raw_materials WHERE LOWER(TRIM(item))='split fogger'")
        def submit(path,cash,bank,quantity="1"):
            return client.post(path,data={"csrf_token":"split-token","purchase_date":"2026-09-06","purchase_invoice":"SPLIT-1","supplier_id":supplier,"material_id":other,"material_name":"Split Fogger","batch_no":"","quantity":quantity,"unit":"Piece","rate":"3400","cash_paid":cash,"bank_paid":bank,"notes":"split"})
        self.assertEqual(submit("/manage/purchase/new","2400","1000").status_code,302)
        with database.get_connection() as c:
            purchase=c.execute("SELECT id,material_id,total_amount,paid_amount,due_amount FROM purchases WHERE purchase_invoice='SPLIT-1'").fetchone();rows=c.execute("SELECT source_table,payment_mode,debit FROM cash_ledger WHERE source_id=? AND source_table LIKE 'purchases_%' ORDER BY source_table",(purchase[0],)).fetchall()
        self.assertEqual(purchase[2:],(3400.0,3400.0,0.0));self.assertEqual([(r[1],r[2]) for r in rows],[('Bank',1000.0),('Cash',2400.0)]);self.assertEqual(self.services.raw_material_stock(purchase[1]),1)
        self.assertEqual(submit(f"/manage/purchase/{purchase[0]}/edit","2000","1400","2").status_code,302)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_id=? AND source_table LIKE 'purchases_%'",(purchase[0],)).fetchone()[0],2)
        ledger=client.get("/cash-bank?mode=Cash&start=2026-09-06&end=2026-09-06");self.assertEqual(ledger.status_code,200);body=ledger.get_data(as_text=True)
        for label in ("Cash Summary","Cash Inflow","Cash Outflow","Cash Balance","Bank Summary","Bank Inflow","Bank Outflow","Bank Balance","Overall Summary","Total Inflow","Total Outflow","Net Balance","Account"):self.assertIn(label,body)
        deleted=client.post(f"/manage/purchase/{purchase[0]}/delete",data={"csrf_token":"split-token"});self.assertEqual(deleted.status_code,302);self.assertEqual(self.services.raw_material_stock(purchase[1]),0)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_id=? AND source_table LIKE 'purchases_%'",(purchase[0],)).fetchone()[0],0)

    def test_cash_bank_dashboard_ui_formatting_filters_table_and_breakpoints(self):
        import web_app
        self.services.set_desktop_role("ADMIN");client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="ledger-ui-token"
        with database.get_connection() as c:
            c.execute("INSERT INTO cash_ledger(transaction_date,transaction_type,reference,payment_mode,debit,credit) VALUES('2026-09-06','UI TEST','CASH-INFLOW','Cash',0,1234567.89)")
            c.execute("INSERT INTO cash_ledger(transaction_date,transaction_type,reference,payment_mode,debit,credit) VALUES('2026-09-06','UI TEST','BANK-OUTFLOW','Bank',2700,0)")
        response=client.get("/cash-bank?mode=Bank&type=UI%20TEST&start=2026-09-06&end=2026-09-06")
        self.assertEqual(response.status_code,200);body=response.get_data(as_text=True)
        for label in ("Cash Summary","Cash Inflow","Cash Outflow","Cash Balance","Bank Summary","Bank Inflow","Bank Outflow","Bank Balance","Overall Summary","Total Inflow","Total Outflow","Net Balance"):
            self.assertEqual(body.count(f">{label}<"),1,label)
        for amount in ("₹1,234,567.89","₹0.00","₹2,700.00","-₹2,700.00","₹1,231,867.89"):
            self.assertIn(amount,body)
        self.assertIn('class="summary-amount is-negative">-₹2,700.00',body)
        self.assertIn('name="start" value="2026-09-06"',body);self.assertIn('name="end" value="2026-09-06"',body)
        self.assertIn('<option selected>Bank</option>',body);self.assertIn('<option selected>UI TEST</option>',body)
        for heading in ("Date","Type","Reference","Mode","Outflow","Inflow"):self.assertIn(f"<th>{heading}</th>",body)
        self.assertIn("BANK-OUTFLOW",body);self.assertNotIn("CASH-INFLOW</td>",body)
        css_response=client.get("/static/mobile.css");css=css_response.get_data(as_text=True);css_response.close()
        self.assertIn(".ledger-summary-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))",css)
        self.assertIn("@media(max-width:900px){.ledger-summary-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}",css)
        self.assertIn("@media(max-width:600px){.ledger-summary-grid{grid-template-columns:1fr}",css)

    def test_sqlite_concurrent_writers(self):
        from concurrent.futures import ThreadPoolExecutor
        self.services.set_desktop_role("ADMIN")
        def write(i):return self.services.save_expense({"expense_date":"2026-09-04","category":"Concurrent","amount":i+1,"payment_mode":"Cash"})
        with ThreadPoolExecutor(max_workers=4) as pool:ids=list(pool.map(write,range(8)))
        self.assertEqual(len(set(ids)),8)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_table='expenses'").fetchone()[0],8);self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0].lower(),"wal")

    def test_production_requires_strong_secret(self):
        import subprocess,sys
        env=os.environ.copy();env["APP_ENV"]="production";env.pop("SECRET_KEY",None);env["MUSHROOM_DATA_DIR"]=self.temp.name
        result=subprocess.run([sys.executable,"-c","import web_app"],cwd=os.path.dirname(__file__),env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn("strong SECRET_KEY",result.stderr)

    def _material(self,name):
        with database.get_connection() as c:return c.execute("SELECT id FROM raw_materials WHERE item=?",(name,)).fetchone()[0]

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

    def test_web_app_loads_without_desktop_ui(self):
        import web_app
        response = web_app.app.test_client().get("/login")
        self.assertEqual(response.status_code, 200)

    def test_invoice_preview_chart_and_report_web_features(self):
        import web_app
        customer,_,_=self.seed()
        with database.get_connection() as c:
            bid=c.execute("SELECT id FROM batches WHERE batch_no='B001'").fetchone()[0]
            c.execute("UPDATE customers SET name=?,address=?,mobile=? WHERE id=?",("Very Long Customer Name "*8,"Long Address "*30,"9999999999",customer))
            c.execute("INSERT INTO purchases(purchase_date,item,quantity,total_amount,batch_no) VALUES('2025-01-01','Old Cost',1,999,'B001')")
        sale=self.services.save_sale({"invoice_no":"INV-PREVIEW","sale_date":"2026-09-04","customer_id":customer,"batch_id":bid,"quantity_kg":2,"rate_per_kg":125,"discount":10,"paid_amount":100,"payment_mode":"UPI","notes":"Handle carefully"})
        client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="feature-token"
        preview=client.get(f"/invoice/{sale}/view");self.assertEqual(preview.status_code,200);body=preview.get_data(as_text=True)
        for value in ("INV-PREVIEW","Very Long Customer Name","B001","2.00","125.00","Cash Paid","Bank / Online Paid","₹100.00","₹140.00","window.print()"):self.assertIn(value,body)
        listing=client.get("/invoices").get_data(as_text=True);self.assertIn('target="_blank"',listing);self.assertIn("Download PDF",listing)
        pdf=client.get(f"/invoice/{sale}.pdf?download=1");self.assertEqual(pdf.status_code,200);self.assertTrue(pdf.data.startswith(b"%PDF"))
        charts=client.get("/charts").get_data(as_text=True);self.assertIn("charts.js",charts);self.assertNotIn("charts.png",charts)
        data=client.get("/api/charts?start=2026-09-01&end=2026-09-30&period=Monthly");self.assertEqual(data.status_code,200);payload=data.get_json();self.assertEqual(len(payload["charts"]),8);self.assertEqual(payload["charts"][0]["datasets"][0]["data"],[240.0]);self.assertEqual(payload["charts"][7]["datasets"][0]["data"],[400.0])
        self.assertTrue(client.get("/api/charts?start=2030-01-01&end=2030-01-02").get_json()["empty"])
        self.assertEqual(client.get("/api/charts?start=bad&end=2030-01-02").status_code,400)
        report=client.get("/reports?start=2026-09-04&end=2026-09-04");self.assertEqual(report.status_code,200);report_body=report.get_data(as_text=True)
        for section in ("Sales","Purchases","Production","Harvest","Expenses","Raw Material Stock","Mushroom Stock Reconciliation","Customer Due","Supplier Due","Labour Due","Cash / Bank","Profit Summary","Batch Report"):self.assertIn(section,report_body)
        csv=client.get("/reports/export.csv?start=2026-09-04&end=2026-09-04");self.assertEqual(csv.status_code,200);self.assertIn(b"Profit Summary",csv.data)
        report_pdf=client.get("/reports/export.pdf?start=2026-09-04&end=2026-09-04");self.assertEqual(report_pdf.status_code,200);self.assertTrue(report_pdf.data.startswith(b"%PDF"))
        css=client.get("/static/mobile.css").get_data(as_text=True);self.assertIn("@media print",css);self.assertIn("grid-template-columns:repeat(2",css)

    def test_hardened_backup_validation_rollback_and_lock(self):
        import io,sqlite3,threading,time
        from unittest import mock
        import web_app
        from backup_service import backup_database,restore_database,validate_backup
        valid=os.path.join(self.temp.name,"valid.db");backup_database(database.DB_FILE,valid);self.assertTrue(validate_backup(valid))
        encoded=os.path.join(self.temp.name,"backup # encoded.db");backup_database(database.DB_FILE,encoded);self.assertTrue(validate_backup(encoded))
        with self.assertRaises(ValueError):backup_database(valid,valid)
        for name,data in (("empty.db",b""),("text.db",b"not sqlite")):
            path=os.path.join(self.temp.name,name)
            with open(path,"wb") as f:f.write(data)
            with self.assertRaises(ValueError):validate_backup(path)
        wrong=os.path.join(self.temp.name,"wrong.db")
        c=sqlite3.connect(wrong);c.execute("CREATE TABLE unrelated(id INTEGER)");c.commit();c.close()
        with self.assertRaises(ValueError):validate_backup(wrong)
        client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="backup-token"
        downloaded=client.get("/backup/download");self.assertEqual(downloaded.status_code,200);self.assertTrue(downloaded.data.startswith(b"SQLite format 3\x00"))
        with mock.patch("werkzeug.datastructures.FileStorage.save",side_effect=OSError("disk full")):
            failed=client.post("/backup/restore",data={"csrf_token":"backup-token","backup":(io.BytesIO(b"SQLite format 3\x00"),"backup.db")},content_type="multipart/form-data",follow_redirects=True)
        self.assertEqual(failed.status_code,200);self.assertIn("previous database was kept unchanged",failed.get_data(as_text=True))
        with database.get_connection() as c:c.execute("UPDATE settings SET value='safe-current' WHERE key='business_name'")
        replacement=os.path.join(self.temp.name,"replacement.db");backup_database(valid,replacement)
        with mock.patch.object(database,"create_database",side_effect=RuntimeError("injected failure")):
            with self.assertRaises(RuntimeError):restore_database(replacement,database.DB_FILE)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT value FROM settings WHERE key='business_name'").fetchone()[0],"safe-current");self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0],"ok");self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(),[])
        entered=threading.Event()
        def connect():
            with database.get_connection():entered.set()
        database.DB_MAINTENANCE_LOCK.acquire()
        try:worker=threading.Thread(target=connect);worker.start();time.sleep(.1);self.assertFalse(entered.is_set())
        finally:database.DB_MAINTENANCE_LOCK.release()
        worker.join(2);self.assertTrue(entered.is_set());self.assertEqual(client.get("/health").status_code,200)
        with database.get_connection() as outer:
            with database.get_connection() as inner:self.assertEqual(inner.execute("SELECT 1").fetchone()[0],1)
            self.assertEqual(outer.execute("SELECT 1").fetchone()[0],1)

    def test_web_backup_routes_do_not_import_desktop_modules(self):
        import builtins,io,sqlite3
        from unittest import mock
        import backup_service,web_app
        client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False};s["csrf_token"]="web-safe-backup-token"
        real_import=builtins.__import__
        attempted=[]
        def web_safe_import(name,*args,**kwargs):
            if name=="tkinter" or name.startswith("tkinter.") or name=="modules.system_tools":
                attempted.append(name)
                raise AssertionError(f"Desktop-only import attempted: {name}")
            return real_import(name,*args,**kwargs)
        with mock.patch("builtins.__import__",side_effect=web_safe_import):
            downloaded=client.get("/backup/download")
        self.assertEqual(downloaded.status_code,200);self.assertEqual(attempted,[])
        path=os.path.join(self.temp.name,"web-download.db")
        with open(path,"wb") as output:output.write(downloaded.data)
        c=sqlite3.connect(path)
        try:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0],"ok")
            self.assertTrue(backup_service.REQUIRED_SCHEMA.keys()<={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")})
        finally:c.close()
        with mock.patch.object(backup_service,"restore_database",return_value=os.path.join(self.temp.name,"safety.db")) as restore:
            with mock.patch("builtins.__import__",side_effect=web_safe_import):
                restored=client.post("/backup/restore",data={"csrf_token":"web-safe-backup-token","backup":(io.BytesIO(downloaded.data),"backup.db")},content_type="multipart/form-data")
        self.assertEqual(restored.status_code,302);self.assertEqual(attempted,[]);restore.assert_called_once()

    def test_owner_capital_complete_lifecycle_and_pnl_isolation(self):
        from capital_service import capital_summary,delete_capital,save_capital
        before=self.services.pnl()
        opening=save_capital({"date":"2026-09-01","kind":"OPENING","cash_amount":20000,"bank_amount":80000})
        introduced=save_capital({"date":"2026-09-02","kind":"INTRODUCED","cash_amount":10000,"bank_amount":20000,"reference":"CAP-1"})
        drawing=save_capital({"date":"2026-09-03","kind":"DRAWING","cash_amount":5000,"bank_amount":0})
        self.assertEqual(capital_summary(),{"opening":100000.0,"introduced":30000.0,"drawings":5000.0,"closing":125000.0})
        self.assertEqual((self.services.cash_balance("Cash"),self.services.cash_balance("Bank")),(25000,100000))
        self.assertEqual(self.services.pnl(),before)
        with database.get_connection() as c:
            rows=c.execute("SELECT transaction_type,payment_mode,debit,credit,source_table FROM cash_ledger ORDER BY id").fetchall()
            self.assertEqual(len(rows),5);self.assertEqual(len({r[4] for r in rows}),5)
            self.assertEqual(dict(c.execute("SELECT key,value FROM settings WHERE key IN ('opening_cash','opening_bank')")),{"opening_cash":"20000.0","opening_bank":"80000.0"})
        save_capital({"date":"2026-09-04","kind":"INTRODUCED","cash_amount":0,"bank_amount":5000},introduced)
        self.assertEqual((self.services.cash_balance("Cash"),self.services.cash_balance("Bank")),(15000,85000))
        delete_capital(drawing);self.assertEqual(self.services.cash_balance("Cash"),20000)
        save_capital({"date":"2026-09-01","kind":"OPENING","cash_amount":1000,"bank_amount":2000},opening)
        self.assertEqual((self.services.cash_balance("Cash"),self.services.cash_balance("Bank")),(1000,7000))
        with self.assertRaises(ValueError):save_capital({"date":"2026-09-05","kind":"OPENING","cash_amount":1,"bank_amount":0})
        delete_capital(opening)
        with database.get_connection() as c:self.assertEqual(dict(c.execute("SELECT key,value FROM settings WHERE key IN ('opening_cash','opening_bank')")),{"opening_cash":"0","opening_bank":"0"})
        self.assertEqual(self.services.pnl(),before)

    def test_capital_validation_reports_charts_and_web_permissions(self):
        from capital_service import save_capital
        from business_reporting import chart_view_model,report_view_model
        for data in (
            {"date":"bad","kind":"INTRODUCED","cash_amount":1,"bank_amount":0},
            {"date":"2026-09-01","kind":"OTHER","cash_amount":1,"bank_amount":0},
            {"date":"2026-09-01","kind":"DRAWING","cash_amount":0,"bank_amount":0},
            {"date":"2026-09-01","kind":"DRAWING","cash_amount":-1,"bank_amount":0},
        ):
            with self.assertRaises(ValueError):save_capital(data)
        save_capital({"date":"2026-09-01","kind":"OPENING","cash_amount":20,"bank_amount":80})
        save_capital({"date":"2026-09-02","kind":"INTRODUCED","cash_amount":10,"bank_amount":20})
        save_capital({"date":"2026-09-03","kind":"DRAWING","cash_amount":5,"bank_amount":10})
        model=report_view_model("2026-09-01","2026-09-30")
        self.assertIn("Capital Report",[s[0] for s in model["sections"]]);self.assertIn("Balance Sheet Foundation",[s[0] for s in model["sections"]])
        chart=next(x for x in chart_view_model("2026-09-01","2026-09-30")["charts"] if x["title"]=="Income vs Expense")
        self.assertEqual(sum(chart["datasets"][0]["data"]),0);self.assertEqual(sum(chart["datasets"][1]["data"]),0)
        import web_app
        client=web_app.app.test_client()
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Staff","role":"STAFF","must_change_password":False};s["csrf_token"]="capital-token"
        self.assertEqual(client.get("/capital").status_code,403)
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Manager","role":"MANAGER","must_change_password":False}
        page=client.get("/capital");self.assertEqual(page.status_code,200);self.assertIn("Closing Capital",page.get_data(as_text=True))
        self.assertEqual(client.post("/capital/new",data={"date":"2026-09-04","kind":"INTRODUCED","cash_amount":"1","bank_amount":"0"}).status_code,400)
        invalid=client.post("/capital/new",data={"csrf_token":"capital-token","date":"bad","kind":"INTRODUCED","cash_amount":"1","bank_amount":"0"})
        self.assertEqual(invalid.status_code,200);self.assertIn("YYYY-MM-DD",invalid.get_data(as_text=True))
        saved=client.post("/capital/new",data={"csrf_token":"capital-token","date":"2026-09-04","kind":"INTRODUCED","cash_amount":"1","bank_amount":"0","reference":"&lt;script&gt;","notes":"<script>alert(1)</script>"})
        self.assertEqual(saved.status_code,302)
        listing=client.get("/capital").get_data(as_text=True);self.assertNotIn("<script>alert(1)</script>",listing)
        with client.session_transaction() as s:s["user"]={"id":1,"name":"Admin","role":"ADMIN","must_change_password":False}
        settings=client.post("/settings",data={"csrf_token":"capital-token","opening_cash":"999","opening_bank":"999","opening_mushroom_stock":"0","expected_rate":"0"},follow_redirects=True)
        self.assertEqual(settings.status_code,200)
        with database.get_connection() as c:self.assertEqual(c.execute("SELECT value FROM settings WHERE key='opening_cash'").fetchone()[0],"20.0")

    def test_capital_component_edit_delete_reconciliation(self):
        from capital_service import delete_capital,save_capital
        for kind in ("INTRODUCED","DRAWING"):
            for component in ("cash_amount","bank_amount"):
                data={"date":"2026-09-05","kind":kind,"cash_amount":0,"bank_amount":0}
                data[component]=40
                entry=save_capital(data)
                expected=40 if kind=="INTRODUCED" else -40
                mode="Cash" if component=="cash_amount" else "Bank"
                self.assertEqual(self.services.cash_balance(mode),expected)
                data[component]=15;save_capital(data,entry)
                self.assertEqual(self.services.cash_balance(mode),15 if kind=="INTRODUCED" else -15)
                with database.get_connection() as c:
                    self.assertEqual(c.execute("SELECT COUNT(*) FROM cash_ledger WHERE source_id=? AND source_table LIKE 'owner_capital_%'",(entry,)).fetchone()[0],1)
                delete_capital(entry);self.assertEqual(self.services.cash_balance(mode),0)

    def test_gui_pages(self):
        try:
            import tkinter as tk, main
            root=tk.Tk();root.withdraw();app=main.MushroomApp(root)
            for name in ("production","harvest","stock","sales","expenses","customers","suppliers","labour","purchases","raw_materials","payments","ledger","batch_cost","profit_loss","reports","charts","backup_restore","settings","users"):
                getattr(app,name)();root.update_idletasks()
            root.destroy()
        except tk.TclError as e:self.skipTest(str(e))


if __name__ == "__main__": unittest.main(verbosity=2)
