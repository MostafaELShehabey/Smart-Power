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
from smart_power.sp_finance.accounts import CUSTODY, holder_account
from smart_power.tests.test_customer_payment import account
from smart_power.tests.utils import load_erpnext_test_data, make_user

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
