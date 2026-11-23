"""Go-live master-data migration (SP-159): each script upserts by its natural key, reports every
row, and a dry run saves nothing."""

import csv
import os
import shutil
import tempfile

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.migration import common, customers, design, items, leads, suppliers, vehicles, workers
from smart_power.tests.test_item_codes import ensure, header
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
MOBILE, OTHER, THIRD = "01001590159", "01101590159", "01201590159"
GROUP, BRAND = "_Test SP159 Panels", "_Test SP159 Brand"


def book(path: str, sheets: dict) -> str:
	from openpyxl import Workbook

	workbook = Workbook()
	workbook.remove(workbook.active)
	for title, rows in sheets.items():
		ws = workbook.create_sheet(title)
		for row in rows:
			ws.append(row)
	workbook.save(path)
	return path


def headers(columns) -> list[str]:
	return [ar for _f, ar, _en in columns]


class MigrationCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.folder = tempfile.mkdtemp(prefix="sp159-")
		self.addCleanup(shutil.rmtree, self.folder, True)

	def path(self, name: str) -> str:
		return os.path.join(self.folder, name)

	def report(self, result: dict) -> list[dict]:
		with open(result["report"], encoding="utf-8-sig") as f:
			return list(csv.DictReader(f))

	def run_script(self, script, path, **kwargs) -> dict:
		return script(path, report=self.path("report.csv"), **kwargs)


class TestCustomers(MigrationCase):
	def setUp(self):
		super().setUp()
		for mobile in (MOBILE, OTHER, THIRD):  # the class shares one transaction
			frappe.db.delete("Customer", {"sp_mobile": mobile})

	def rows(self):
		return [
			headers(customers.COLUMNS),
			["SP159 عميل أول", "+20 100 159 0159", "", "فرد", "", "", ""],
			["SP159 نفس العميل", "01001590159", OTHER, "", "", "نعم", ""],
			["SP159 بلا موبايل", "123", "", "", "", "", ""],
			["SP159 عميل ثاني", THIRD, "", "شركة", "", "", ""],
		]

	def test_the_dry_run_lists_the_duplicates_and_saves_nothing(self):
		path = book(self.path("customers.xlsx"), {"Sheet": self.rows()})
		result = self.run_script(customers.run, path)
		self.assertEqual(
			(result["source_rows"], result["created"], result["merged"], result["error"]), (4, 2, 1, 1)
		)
		lines = {int(r["row"]): r for r in self.report(result)}
		self.assertEqual((lines[3]["action"], lines[3]["key"]), ("merged", MOBILE))
		self.assertEqual(lines[4]["action"], "error")
		self.assertFalse(frappe.db.exists("Customer", {"sp_mobile": MOBILE}))

	def test_one_customer_per_mobile_and_a_second_run_changes_nothing(self):
		path = book(self.path("customers.xlsx"), {"Sheet": self.rows()})
		self.run_script(customers.run, path, dry_run=0)
		found = frappe.get_all(
			"Customer",
			{"sp_mobile": MOBILE},
			["name", "customer_name", "sp_mobile_2", "sp_featured", "sp_tier"],
		)
		self.assertEqual(len(found), 1)
		self.assertEqual(
			(found[0].customer_name, found[0].sp_mobile_2, found[0].sp_featured, found[0].sp_tier),
			("SP159 عميل أول", OTHER, 1, "Individual"),  # the first name; the blanks from the second row
		)
		self.assertEqual(frappe.db.get_value("Customer", {"sp_mobile": THIRD}, "sp_tier"), "Company")
		again = self.run_script(customers.run, path, dry_run=0)
		self.assertEqual((again["created"], again["updated"], again["unchanged"]), (0, 0, 2))

	def test_the_statement_customers_load_featured(self):
		station = [
			[None],
			[None, "تاريخ التعاقد"],
			[None, "العميل", "SP159 عميل محطة"],
			[None, "رقم التليفون", f"{MOBILE} / {OTHER}"],
		]
		no_phone = [[None], [None, "العميل", "SP159 محطة بلا رقم"], [None, "رقم التليفون", None]]
		as_number = [[None], [None, "العميل", "SP159 رقم بلا صفر"], [None, "رقم التليفون", int(THIRD)]]
		path = book(
			self.path("statement.xlsx"),
			{
				"محطة (1)": station,
				"محطة (2)": no_phone,
				"محطة (3)": as_number,
				"ميزان الحركة": [["المحطة"], ["1"]],
			},
		)
		result = self.run_script(customers.from_statement, path, dry_run=0)
		self.assertEqual((result["source_rows"], result["created"], result["error"]), (3, 2, 1))
		self.assertTrue(frappe.db.exists("Customer", {"sp_mobile": THIRD}))  # Excel dropped its 0
		customer = frappe.db.get_value(
			"Customer", {"sp_mobile": MOBILE}, ["sp_featured", "sp_mobile_2"], as_dict=True
		)
		self.assertEqual((customer.sp_featured, customer.sp_mobile_2), (1, OTHER))
		missing = next(r for r in self.report(result) if r["action"] == "error")
		self.assertEqual(missing["sheet"], "محطة (2)")


class TestSuppliersWorkersVehicles(MigrationCase):
	def test_suppliers_match_their_other_spellings_and_flag_the_consignment_owner(self):
		existing = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "SP159 Africa",
				"supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}),
				"sp_aliases": "افريقيا سيستم",
			}
		).insert()
		path = book(
			self.path("suppliers.xlsx"),
			{
				"Sheet": [
					headers(suppliers.COLUMNS),
					["افريقيا  سيستم", "", "", "", "", "", "نعم", ""],
					["SP159 New Supplier", "", "", "", "", "30 يوم", "", ""],
				]
			},
		)
		result = self.run_script(suppliers.run, path, dry_run=0)
		self.assertEqual((result["updated"], result["created"]), (1, 1))
		self.assertEqual(frappe.db.get_value("Supplier", existing.name, "sp_is_consignment_owner"), 1)
		self.assertEqual(
			frappe.db.get_value("Supplier", {"supplier_name": "SP159 New Supplier"}, "sp_terms_note"),
			"30 يوم",
		)

	def test_workers_and_vehicles_upsert_by_mobile_and_plate(self):
		path = book(
			self.path("workers.xlsx"),
			{
				"Sheet": [
					headers(workers.COLUMNS),
					["SP159 عامل", MOBILE, "نعم", 250, "", "", ""],
					["SP159 بلا اسم صالح", "999", "", "", "", "", ""],
				]
			},
		)
		first = self.run_script(workers.run, path, dry_run=0, company=COMPANY)
		self.assertEqual((first["created"], first["error"]), (1, 1))
		worker = frappe.db.get_value(
			"Employee", {"cell_number": MOBILE}, ["sp_is_daily_worker", "sp_daily_wage"], as_dict=True
		)
		self.assertEqual((worker.sp_is_daily_worker, worker.sp_daily_wage), (1, 250))
		self.assertEqual(self.run_script(workers.run, path, dry_run=0, company=COMPANY)["unchanged"], 1)

		plate = "SP159-WINCH"
		rows = [headers(vehicles.COLUMNS), [plate, "ونش", 12000, 5000, 10000, "", ""]]
		self.run_script(vehicles.run, book(self.path("v1.xlsx"), {"Sheet": rows}), dry_run=0, company=COMPANY)
		self.assertEqual(
			frappe.db.get_value("Vehicle", plate, ["sp_vehicle_type", "sp_odometer_km"]), ("Winch", 12000)
		)
		rows[1][2] = 12500  # the count on the day wins
		again = self.run_script(
			vehicles.run, book(self.path("v2.xlsx"), {"Sheet": rows}), dry_run=0, company=COMPANY
		)
		self.assertEqual(again["updated"], 1)
		self.assertEqual(frappe.db.get_value("Vehicle", plate, "sp_odometer_km"), 12500)


class TestLeadsItemsDesign(MigrationCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		root = (
			frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ("in", ("", None))})
			or "All Item Groups"
		)
		ensure(
			"Item Group",
			GROUP,
			item_group_name=GROUP,
			parent_item_group=root,
			sp_code_prefix="PNM",
			sp_required_specs="sp_watt",
		)
		ensure("Brand", BRAND, brand=BRAND, sp_code="T159")
		cls.agent = make_user("sp.mig.agent@example.com", ("marketing_agent",))

	def test_leads_are_the_agents_and_a_known_mobile_is_skipped(self):
		frappe.get_doc({"doctype": "Customer", "customer_name": "SP159 Known", "sp_mobile": THIRD}).insert()
		path = book(
			self.path("leads.xlsx"),
			{"Sheet": [["الاسم", "الموبايل"], ["SP159 عميل محتمل", MOBILE], ["SP159 عميل حالي", THIRD]]},
		)
		result = self.run_script(leads.run, path, owner=self.agent, dry_run=0)
		self.assertEqual((result["created"], result["skipped"]), (1, 1))
		self.assertEqual(frappe.db.get_value("Lead", {"sp_mobile": MOBILE}, "owner"), self.agent)

	def test_items_come_through_the_group_template_and_design_fills_their_specs(self):
		rows = [
			header(GROUP, "sp_model", "sp_name_ar", "brand", "stock_uom", "sp_watt"),
			["STP 159", "لوح 159", BRAND, "Nos", 340],
			["", "بلا موديل", BRAND, "Nos", 340],
		]
		path = book(self.path("items.xlsx"), {"PNM": rows})
		dry = self.run_script(items.run, path)
		self.assertEqual((dry["created"], dry["error"]), (1, 1))
		self.assertFalse(frappe.db.exists("Item", "PNM-T159-STP159"))
		self.run_script(items.run, path, dry_run=0)
		self.assertTrue(frappe.db.exists("Item", "PNM-T159-STP159"))

		panel = [
			[None],
			[None],
			[None],
			[None, "BRANDE", BRAND],
			[None],
			[None, "COMPANY"],
			[None, "MODULE", "stp159"],
			[None, "TYPE", "POLY"],
		]
		panel += [
			[None, "Maximum Power", 345],
			[None, "Optimum Operating Voltage", 37.9],
			[None, "Optimum Operating Current", 8.98],
		]
		panel += [[None, "Open Circuit Voltage", 46], [None, "Short Circuit Current", 9.5], [None, "MODULE"]]
		panel[6] += ["NO SUCH MODEL"]
		result = self.run_script(
			design.run, book(self.path("design.xlsx"), {"PANEL": panel, "DRIVE": []}), dry_run=0
		)
		self.assertEqual((result["updated"], result["skipped"]), (1, 1))
		item = frappe.get_doc("Item", "PNM-T159-STP159")
		self.assertEqual(
			(item.sp_watt, item.sp_vmp, item.sp_imp, item.sp_voc, item.sp_isc), (345, 37.9, 8.98, 46, 9.5)
		)
		again = self.run_script(
			design.run, book(self.path("design2.xlsx"), {"PANEL": panel, "DRIVE": []}), dry_run=0
		)
		self.assertEqual(again["unchanged"], 1)

	def test_only_the_admin_runs_a_migration(self):
		path = book(self.path("customers.xlsx"), {"Sheet": [headers(customers.COLUMNS)]})
		frappe.set_user(self.agent)
		self.assertRaises(frappe.PermissionError, customers.run, path)
		frappe.set_user("Administrator")
		self.assertEqual(common.template(customers.COLUMNS, self.path("t.xlsx")), self.path("t.xlsx"))
