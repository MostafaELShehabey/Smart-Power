"""A15 Opening balances (SP-160): check the cutover workbook, post it once, reconcile it.

The opening is dated to a past year with nothing else on it, so the trial balance on that day is
the opening alone and must match the template line by line.
"""

import io
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_finance import opening as ob
from smart_power.sp_finance.accounts import CUSTODY, holder_account, seed_accounts
from smart_power.tests.test_customer_payment import account
from smart_power.tests.utils import load_erpnext_test_data, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"
ON = "2012-01-01"
BANK, WINCH = 100000, 250000  # the bank's balance; the winch at book value
CUSTOMER_OWES, SUPPLIER_OWED = 40000, 30000
QTY, RATE = 10, 1500  # the counted stock
CUSTODY_OPEN = 5000
STOCKLESS = BANK + WINCH + CUSTOMER_OWES + CUSTODY_OPEN - SUPPLIER_OWED


def equity() -> float:
	"""The balancing figure; the stock counts only when the company posts it to the ledger."""
	from erpnext import is_perpetual_inventory_enabled

	stock = QTY * RATE if is_perpetual_inventory_enabled(COMPANY) else 0
	return BANK + WINCH + CUSTOMER_OWES + stock + CUSTODY_OPEN - SUPPLIER_OWED


def workbook(sheets: dict) -> bytes:
	"""A filled template: each sheet's header row and hint row, then the given rows."""
	from openpyxl import Workbook

	book = Workbook()
	book.remove(book.active)
	for sheet, columns in ob.SHEETS.items():
		ws = book.create_sheet(sheet)
		keys = [k for k, _h in columns]
		ws.append(keys)
		ws.append([f"{ob.HINT} hint"] + [""] * (len(keys) - 1))
		for row in sheets.get(sheet, []):
			ws.append([row.get(k) for k in keys])
	out = io.BytesIO()
	book.save(out)
	return out.getvalue()


class OpeningCase(IntegrationTestCase):
	"""The shared setup. Each test class subclasses this, not another test class: Frappe marks a
	class as set up, and a subclass inheriting that mark skips its own setup and its rollback."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_accounts(COMPANY)  # the Custody group, on a fresh site
		cls.bank = account("SP OB Bank", "Bank", "Official", account_type="Bank")
		cls.holder = make_user("sp.ob.holder@example.com", ("custody_holder",))
		holder_account(cls.holder, CUSTODY, COMPANY)  # the trial balance names it
		if not frappe.db.exists("Item", "SP-OB-PANEL"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": "SP-OB-PANEL",
					"item_name": "لوح اختبار الافتتاح",
					"item_group": "_Test Item Group",
					"stock_uom": "Nos",
					"is_stock_item": 1,
				}
			).insert()
		cls.consignor = frappe.db.get_value("Supplier", {"supplier_name": "SP OB Consignor"}) or (
			frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": "SP OB Consignor",
					"supplier_group": "_Test Supplier Group",
					"sp_is_consignment_owner": 1,
				}
			)
			.insert()
			.name
		)

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete(ob.OPENING, {"company": COMPANY})
		self.doc = frappe.get_doc({"doctype": ob.OPENING, "company": COMPANY, "opening_date": ON}).insert()

	def sheets(self, **override) -> dict:
		sheets = {
			ob.ACCOUNTS: [
				{"account": self.bank, "debit": BANK},
				{"account": "Capital Equipment - _TC", "debit": WINCH, "note": "the winch"},
			],
			ob.CUSTODY: [{"holder": self.holder, "amount": CUSTODY_OPEN}],
			ob.CUSTOMERS: [{"customer": "_Test Customer", "amount": CUSTOMER_OWES}],
			ob.SUPPLIERS: [{"supplier": "_Test Supplier", "amount": SUPPLIER_OWED, "bill_no": "B-1"}],
			ob.STOCK: [
				{"warehouse": "Stores - _TC", "item_code": "SP-OB-PANEL", "qty": QTY, "valuation_rate": RATE}
			],
			ob.CONSIGNMENT: [
				{"supplier": self.consignor, "item_code": "SP-OB-PANEL", "pallets": 2, "per_pallet": 31}
			],
		}
		custody = frappe.db.get_value(
			"Account", {"company": COMPANY, "sp_holder": self.holder, "sp_account_kind": "Custody"}
		)
		sheets[ob.TRIAL] = [
			{"account": self.bank, "debit": BANK},
			{"account": "Capital Equipment - _TC", "debit": WINCH},
			{"account": "Debtors - _TC", "debit": CUSTOMER_OWES},
			*([{"account": "Stock In Hand - _TC", "debit": QTY * RATE}] if equity() > STOCKLESS else []),
			{"account": "Creditors - _TC", "credit": SUPPLIER_OWED},
			{"account": "Opening Balance Equity - _TC", "credit": equity()},
			{"account": custody, "debit": CUSTODY_OPEN},
		]
		sheets.update(override)
		return sheets

	def check(self, sheets: dict) -> dict:
		with patch.object(ob, "_content", return_value=workbook(sheets)):
			return ob.run_check(self.doc.name)

	def post(self, sheets: dict) -> None:
		with patch.object(ob, "_content", return_value=workbook(sheets)):
			ob.run_check(self.doc.name)
			ob.post(self.doc.name)
		self.doc.reload()


class TestOpeningBalance(OpeningCase):
	def test_a_clean_workbook_checks_with_the_equity_as_the_balancing_figure(self):
		result = self.check(self.sheets())
		self.assertEqual(result["errors"], [])
		self.assertEqual(result["equity"], equity())
		self.assertEqual(frappe.db.get_value(ob.OPENING, self.doc.name, "status"), ob.CHECKED)

	def test_each_problem_is_named_with_its_sheet_and_row(self):
		result = self.check(
			self.sheets(
				**{
					ob.ACCOUNTS: [
						{"account": "No Such Account", "debit": 1},
						{"account": "Debtors - _TC", "debit": 1},
						{"account": self.bank, "debit": 1, "credit": 1},
					],
					ob.CUSTOMERS: [{"customer": "No Such Customer", "amount": 5}],
				}
			)
		)
		rows = {(e["sheet"], e["row"]) for e in result["errors"]}
		self.assertTrue({(ob.ACCOUNTS, 3), (ob.ACCOUNTS, 4), (ob.ACCOUNTS, 5), (ob.CUSTOMERS, 3)} <= rows)
		self.assertEqual(frappe.db.get_value(ob.OPENING, self.doc.name, "status"), ob.DRAFT)

	def test_it_is_posted_once(self):
		sheets = self.sheets(**{ob.STOCK: [], ob.TRIAL: []})  # the class shares one transaction
		self.post(sheets)
		with patch.object(ob, "_content", return_value=workbook(sheets)):
			self.assertRaises(frappe.ValidationError, ob.post, self.doc.name)
		self.assertRaises(frappe.ValidationError, self.doc.delete)

	def test_a_changed_workbook_must_be_checked_again(self):
		self.check(self.sheets())
		changed = self.sheets(**{ob.CUSTOMERS: [{"customer": "_Test Customer", "amount": 1}]})
		with patch.object(ob, "_content", return_value=workbook(changed)):
			self.assertRaises(frappe.ValidationError, ob.post, self.doc.name)

	def test_only_the_admin_posts(self):
		self.check(self.sheets())
		frappe.set_user(make_user("sp.ob.accountant@example.com", ("accountant",)))
		self.assertRaises(frappe.PermissionError, ob.post, self.doc.name)

	def test_custody_from_temporary_opening_is_refused_outside_the_opening(self):
		custody = frappe.get_doc(
			{
				"doctype": "SP Custody",
				"holder": self.holder,
				"company": COMPANY,
				"given_on": ON,
				"from_account": "Temporary Opening - _TC",
				"amount": 100,
			}
		)
		self.assertRaises(frappe.ValidationError, custody.insert)


class TestOpeningBalancePosted(OpeningCase):
	"""The full posting, in a class of its own: the other class posts too, in its transaction."""

	def test_posting_opens_every_section_and_matches_the_trial_balance(self):
		self.post(self.sheets())
		self.assertEqual(self.doc.status, ob.POSTED)
		kinds = {d.reference_doctype for d in self.doc.documents}
		self.assertTrue(
			{
				"Journal Entry",
				"Sales Invoice",
				"Purchase Invoice",
				"Stock Reconciliation",
				"SP Consignment Container",
				"SP Custody",
			}
			<= kinds
		)
		invoice = next(d.reference_name for d in self.doc.documents if d.reference_doctype == "Sales Invoice")
		self.assertTrue(invoice.startswith("OPN-SI-_TC-2012-"))
		self.assertEqual(
			flt(frappe.db.get_value("Sales Invoice", invoice, "outstanding_amount")), CUSTOMER_OWES
		)
		custody = next(d.reference_name for d in self.doc.documents if d.reference_doctype == "SP Custody")
		self.assertEqual(frappe.db.get_value("SP Custody", custody, "status"), "Given")
		temporary = frappe.db.sql(
			"""select sum(debit - credit) from `tabGL Entry` where account = 'Temporary Opening - _TC'
			and posting_date <= %s and is_cancelled = 0""",
			ON,
		)[0][0]
		self.assertAlmostEqual(flt(temporary), 0)
		entries = [d.reference_name for d in self.doc.documents if d.reference_doctype == "Journal Entry"]
		self.assertFalse(  # the opening is not a manual entry for the review centre
			frappe.db.exists(
				"SP Review Item", {"reference_name": ("in", entries), "category": "Manual Entry"}
			)
		)
		with patch.object(ob, "_content", return_value=workbook(self.sheets())):
			result = ob.reconcile(self.doc.name)
		self.assertTrue(result["matches"], [r for r in result["rows"] if not r["matches"]])


AGRI_BANK = "SP OB Agri Bank"
WINCH_PLATE = "SP160-WINCH"
LEFT, FIRST, SECOND = 60000, 25000, 35000  # what the open station still owes, in two instalments
AGREED, PAID = 100000, 40000  # Agreed and paid to date: the contract, and what was paid before
ADVANCE_LEFT, WINCH_OWED = 20000, 3000
DUE_FIRST, DUE_SECOND = "2012-03-01", "2012-06-01"


class StationsCase(OpeningCase):
	"""The open stations, their advances and the winch debts (part 2)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from smart_power.sp_finance import advances
		from smart_power.sp_finance.centers import seed_centers
		from smart_power.sp_stock import warehouses as wh
		from smart_power.sp_winch import field_entry as fe

		wh.seed_warehouses(COMPANY)
		seed_centers(COMPANY)
		set_setting(account_map=[])  # the site's own company maps the same events
		advances.seed_account_map(COMPANY)
		fe.seed_account_map(COMPANY)
		if not frappe.db.exists("Bank", AGRI_BANK):
			frappe.get_doc({"doctype": "Bank", "bank_name": AGRI_BANK}).insert()
		if not frappe.db.exists("Vehicle", WINCH_PLATE):
			frappe.get_doc(
				{
					"doctype": "Vehicle",
					"license_plate": WINCH_PLATE,
					"sp_vehicle_type": "Winch",
					"company": COMPANY,
				}
			).insert()
		cls.collector = make_user("sp.ob.collector@example.com", ("accountant",))

	def setUp(self):
		super().setUp()
		frappe.db.delete("SP Cheque", {"cheque_no": ("like", "SP160-%")})

	def station_sheets(self, mode_rows: dict, cheques=True) -> dict:
		return {
			ob.STATIONS: [
				{"ref": "S1", "customer": "_Test Customer", "collection_owner": self.collector, **mode_rows}
			],
			ob.INSTALLMENTS: [
				{"station": "S1", "due_date": DUE_SECOND, "amount": SECOND},
				{"station": "S1", "due_date": DUE_FIRST, "amount": FIRST},
			],
			ob.CHEQUES: [
				{
					"station": "S1",
					"cheque_no": "SP160-1",
					"bank": "البريد",
					"due_date": DUE_FIRST,
					"amount": FIRST,
				}
			]
			if cheques
			else [],
		}

	def posted(self, doctype: str) -> list[str]:
		return [d.reference_name for d in self.doc.documents if d.reference_doctype == doctype]


class TestOpeningStations(StationsCase):
	def test_an_open_station_shows_its_two_instalments_and_cheque_in_collections(self):
		from smart_power.sp_stations.collections import collections
		from smart_power.sp_winch.receivables import receivables

		sheets = self.station_sheets({"remaining": LEFT, "contract_date": "2011-10-01"})
		sheets[ob.ADVANCES] = [{"station": "S1", "bank": AGRI_BANK, "amount": ADVANCE_LEFT}]
		sheets[ob.WINCH] = [
			{
				"customer_name": "SP OB Winch Debtor",
				"phone": "01001600160",
				"amount": WINCH_OWED,
				"debt_date": "2011-11-15",
				"vehicle": WINCH_PLATE,
			}
		]
		advances = frappe.db.get_value(
			"Account", {"company": COMPANY, "account_name": "Customer Advances - Agri Bank"}
		)
		sheets[ob.TRIAL] = [
			{"account": advances, "debit": ADVANCE_LEFT},
			{"account": "Debtors - _TC", "debit": WINCH_OWED},
			{"account": "Opening Balance Equity - _TC", "credit": ADVANCE_LEFT + WINCH_OWED},
		]
		self.assertEqual(self.check(sheets)["errors"], [])
		self.post(sheets)
		self.assertEqual(self.doc.status, ob.POSTED)

		station = frappe.get_doc("SP Station", self.posted("SP Station")[0])
		self.assertTrue(station.project and station.sales_order)
		self.assertEqual(station.collection_owner, self.collector)
		self.assertEqual((flt(station.agreed_amount), flt(station.paid_amount)), (LEFT, 0))
		self.assertEqual(flt(station.remaining_amount), LEFT)
		row = next(r for r in collections()["stations"] if r["station"] == station.name)
		self.assertEqual(
			[(str(r["due_date"]), r["amount"]) for r in row["schedule"]],
			[(DUE_FIRST, FIRST), (DUE_SECOND, SECOND)],
		)
		self.assertEqual([(c.cheque_no, flt(c.amount)) for c in row["cheques"]], [("SP160-1", FIRST)])

		advance = frappe.get_doc("SP Customer Advance", self.posted("SP Customer Advance")[0])
		self.assertEqual((advance.status, flt(advance.outstanding_amount)), ("Open", ADVANCE_LEFT))

		job = frappe.get_doc("SP Field Entry", self.posted("SP Field Entry")[0])
		self.assertTrue(job.is_opening)
		self.assertEqual((job.payment_status, flt(job.outstanding_amount)), ("Open", WINCH_OWED))
		owed = {r["phone"]: r for r in receivables()["customers"]}
		self.assertIn("01001600160", owed)

		with patch.object(ob, "_content", return_value=workbook(sheets)):
			result = ob.reconcile(self.doc.name)
		self.assertTrue(result["matches"], [r for r in result["rows"] if not r["matches"]])

	def test_the_instalments_must_add_up_to_what_is_left(self):
		sheets = self.station_sheets({"remaining": LEFT + 1})
		result = self.check(sheets)
		self.assertIn((ob.STATIONS, 3), {(e["sheet"], e["row"]) for e in result["errors"]})
		sheets = self.station_sheets({"remaining": LEFT})
		sheets[ob.CHEQUES].append(dict(sheets[ob.CHEQUES][0]))
		sheets[ob.INSTALLMENTS].append({"station": "S9", "due_date": DUE_FIRST, "amount": 1})
		rows = {(e["sheet"], e["row"]) for e in self.check(sheets)["errors"]}
		self.assertTrue({(ob.CHEQUES, 4), (ob.INSTALLMENTS, 5)} <= rows)

	def test_an_opening_winch_job_is_made_only_by_the_opening(self):
		job = frappe.get_doc(
			{
				"doctype": "SP Field Entry",
				"entry_kind": "Job",
				"for_kind": "Outside",
				"vehicle": WINCH_PLATE,
				"work_date": ON,
				"customer_name": "SP OB Winch Debtor",
				"customer_phone": "01001600160",
				"is_opening": 1,
				"agreed_amount": 1,
			}
		)
		self.assertRaises(frappe.MandatoryError, job.insert)  # a normal job, which names its type


class TestOpeningPaidToDate(StationsCase):
	def test_agreed_and_paid_to_date_counts_the_paid_money_on_the_station(self):
		self.doc.db_set("station_mode", ob.AGREED_AND_PAID)
		self.doc.reload()
		sheets = self.station_sheets(
			{"agreed": AGREED, "paid": PAID, "contract_date": "2011-10-01"}, cheques=False
		)
		self.post(sheets)
		self.assertEqual(self.doc.status, ob.POSTED)
		station = frappe.get_doc("SP Station", self.posted("SP Station")[0])
		self.assertEqual(
			(flt(station.agreed_amount), flt(station.paid_amount), flt(station.remaining_amount)),
			(AGREED, PAID, AGREED - PAID),
		)
		self.assertEqual((str(station.next_due_date), flt(station.next_due_amount)), (DUE_FIRST, FIRST))
		owed_back = frappe.db.sql(
			"""select sum(credit - debit) from `tabGL Entry` where party = '_Test Customer'
			and project = %s and is_cancelled = 0""",
			station.project,
		)[0][0]
		self.assertEqual(flt(owed_back), PAID)  # on Debtors, for the final invoice to take
