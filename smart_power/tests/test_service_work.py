"""SV2 Service and warranty (SP-99): installations log work and parts on the ticket; a part is
issued from stock to the station, an out-of-warranty charge becomes a draft income record, and a
supplier claim is record-only."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, flt, today

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_finance.centers import seed_centers
from smart_power.sp_site import service as sv
from smart_power.sp_site.site_log import seed_account_map
from smart_power.sp_stock import warehouses as wh
from smart_power.sp_stock import warranty
from smart_power.tests.test_field_entry import list_value
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
PART, STOCKED, RATE, CHARGE = "_Test Item", 10, 500, 1200


class TestServiceWork(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		seed_centers(COMPANY)
		set_setting(account_map=[])
		seed_account_map(COMPANY)
		cls.camelia = make_user("sp.sw.camelia@example.com", ("lead_intake", "customer_followup"))
		cls.mostafa = make_user("sp.sw.mostafa@example.com", ("installation_manager", "warranty_service"))
		cls.accountant = make_user("sp.sw.accountant@example.com", ("accountant",))
		cls.issue = list_value("Service Issue", "INVERTER_FAULT")
		if not frappe.db.exists(
			"SP List Value", {"list_name": "Simple Record Type", "code": "SERVICE_CHARGE"}
		):
			frappe.get_doc(
				{
					"doctype": "SP List Value",
					"list_name": "Simple Record Type",
					"code": "SERVICE_CHARGE",
					"value_ar": "رسوم صيانة",
					"meta_json": '{"account": "Other Income", "direction": "In"}',
				}
			).insert()
		cls.main = wh.warehouse_of(COMPANY, wh.MAIN)
		frappe.get_doc(
			{
				"doctype": "Stock Entry",
				"stock_entry_type": "Material Receipt",
				"purpose": "Material Receipt",
				"company": COMPANY,
				"items": [{"item_code": PART, "qty": STOCKED, "t_warehouse": cls.main, "basic_rate": RATE}],
			}
		).submit()
		cls.station = (
			frappe.get_doc({"doctype": "SP Station", "customer": "_Test Customer", "company": COMPANY})
			.insert()
			.name
		)
		warranty.upsert(
			"SP99-INV-1",
			PART,
			{
				"station": cls.station,
				"source": "Station",
				"start_date": add_months(today(), -30),
				"months": 36,
			},
		)

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def accepted_ticket(self):
		frappe.set_user(self.camelia)
		doc = frappe.get_doc(
			{
				"doctype": sv.TICKET,
				"customer": "_Test Customer",
				"station": self.station,
				"issue_type": self.issue,
			}
		).insert()
		frappe.set_user(self.mostafa)
		sv.move(doc.name, sv.ACCEPTED)
		return frappe.get_doc(sv.TICKET, doc.name)

	def stock(self):
		return flt(frappe.db.get_value("Bin", {"item_code": PART, "warehouse": self.main}, "actual_qty"))

	def test_a_part_in_warranty_leaves_the_main_store_onto_the_station(self):
		doc = self.accepted_ticket()
		before = self.stock()
		doc.append(
			"work_log",
			{
				"work_type": "Site visit",
				"notes": "تغيير كارت",
				"hours": 2,
				"item": PART,
				"qty": 1,
				"in_warranty": 1,
			},
		)
		doc.save()
		doc.reload()
		row = doc.work_log[0]
		self.assertEqual((row.warehouse, row.logged_by), (self.main, self.mostafa))
		self.assertTrue(row.stock_entry)
		self.assertFalse(row.income_record)
		self.assertEqual(self.stock(), before - 1)
		entry = frappe.get_doc("Stock Entry", row.stock_entry)
		self.assertEqual(
			(entry.docstatus, entry.project), (1, frappe.db.get_value("SP Station", self.station, "project"))
		)
		doc.save()  # saving again issues nothing more
		self.assertEqual(self.stock(), before - 1)
		doc.work_log[0].qty = 3
		self.assertRaises(frappe.ValidationError, doc.save)  # an issued line no longer changes

	def test_out_of_warranty_work_raises_a_draft_income_record_for_the_accountant(self):
		doc = self.accepted_ticket()
		doc.append(
			"work_log",
			{"work_type": "Remote", "notes": "ضبط إعدادات", "in_warranty": 0, "charge_amount": CHARGE},
		)
		doc.save()
		doc.reload()
		record = frappe.get_doc(sv.RECORD, doc.work_log[0].income_record)
		self.assertEqual((record.docstatus, flt(record.amount), record.station), (0, CHARGE, self.station))
		self.assertTrue(
			frappe.db.exists(
				"SP Task", {"reference_name": record.name, "assigned_to": self.accountant, "status": "Open"}
			)
		)
		self.assertFalse(doc.work_log[0].stock_entry)  # no part, nothing issued

	def test_only_installations_log_work_and_only_on_an_accepted_ticket(self):
		doc = self.accepted_ticket()
		frappe.set_user(self.camelia)
		mine = frappe.get_doc(sv.TICKET, doc.name)
		mine.append("work_log", {"work_type": "Remote", "notes": "x"})
		self.assertRaises(frappe.PermissionError, mine.save)
		mine.reload()
		mine.description = "العميل اتصل مرة ثانية"  # she still edits her own ticket
		mine.save()
		opened = frappe.get_doc(
			{
				"doctype": sv.TICKET,
				"customer": "_Test Customer",
				"station": self.station,
				"issue_type": self.issue,
			}
		).insert()
		frappe.set_user(self.mostafa)
		opened = frappe.get_doc(sv.TICKET, opened.name)
		opened.append("work_log", {"work_type": "Remote", "notes": "x"})
		self.assertRaises(frappe.ValidationError, opened.save)  # accept it first

	def test_a_supplier_claim_is_linked_to_the_ticket_with_no_entry(self):
		doc = self.accepted_ticket()
		entries = frappe.db.count("GL Entry")
		claim = frappe.get_doc(
			{
				"doctype": sv.CLAIM,
				"ticket": doc.name,
				"supplier": "_Test Supplier",
				"item": PART,
				"serial_no": "SP99-INV-1",
				"description": "كارت تالف",
			}
		).insert()
		self.assertEqual((claim.status, claim.station), ("Logged", self.station))
		self.assertTrue(claim.warranty_end)
		self.assertEqual(frappe.db.count("GL Entry"), entries)
