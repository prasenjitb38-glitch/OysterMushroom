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
            for table in ("customer_payments","supplier_payments","labour_payments","cash_ledger","sales","harvests","daily_production","purchases","expenses","labour","material_usage","material_adjustments","customers","suppliers","batches","stock_transactions"):
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
        from modules.sales import generate_invoice_pdf_file
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
        from modules.system_tools import backup_database,restore_database
        working=os.path.join(self.temp.name,"working.db");backup=os.path.join(self.temp.name,"backup.db");shutil.copy2(database.DB_FILE,working);backup_database(working,backup)
        with sqlite3.connect(working) as c:c.execute("INSERT INTO settings(key,value) VALUES('roundtrip','changed') ON CONFLICT(key) DO UPDATE SET value='changed'")
        restore_database(backup,working)
        with sqlite3.connect(working) as c:self.assertIsNone(c.execute("SELECT value FROM settings WHERE key='roundtrip'").fetchone());self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0],"ok");self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_dashboard_event_callback(self):
        from events import subscribe,unsubscribe,publish
        seen=[]
        def callback(event):seen.append(event)
        subscribe(callback);publish("sale_changed");unsubscribe(callback);self.assertEqual(seen,["sale_changed"])

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
            "MANAGER":{"dashboard","production","harvest","stock","sales","raw_materials_web","purchases_web","expenses_web","customers_web","suppliers_web","labour_web","payments_web","ledger_web","pnl_web","reports_web","charts_web","invoices_web"},
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

    def test_gui_pages(self):
        try:
            import tkinter as tk, main
            root=tk.Tk();root.withdraw();app=main.MushroomApp(root)
            for name in ("production","harvest","stock","sales","expenses","customers","suppliers","labour","purchases","raw_materials","payments","ledger","batch_cost","profit_loss","reports","charts","backup_restore","settings","users"):
                getattr(app,name)();root.update_idletasks()
            root.destroy()
        except tk.TclError as e:self.skipTest(str(e))


if __name__ == "__main__": unittest.main(verbosity=2)
