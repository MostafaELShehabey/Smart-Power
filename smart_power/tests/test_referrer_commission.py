"""The referrer's lump-sum commission (SP-177): hidden on paper, in the cost, owed to the referrer."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt, today

from smart_power.sp_finance.accounts import seed_accounts
from smart_power.sp_quotes.special_lines import COMMISSION
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations import commission as cm
from smart_power.sp_stations.costing import actual_cost
from smart_power.sp_stations.deposit import run_deposit
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY, STATION = "_Test Company", "SP Station"
COMMISSION_AMOUNT = 10000
AGRI_BANK = "Financing Type-AGRI"


def referrer(name="م. محمد سليمان سيد", mobile="01012345677"):
	existing = frappe.db.get_value("Sales Partner", {"sp_mobile": mobile})
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "Sales Partner",
				"partner_name": name,
				"sp_mobile": mobile,
				"commission_rate": 0,
				"territory": frappe.db.get_value("Territory", {"is_group": 0}) or "All Territories",
			}
		)
		.insert()
		.name
	)


def commission_cost(station: str) -> float:
	"""The commission line of the station's actual cost (the Costs tab, SP-76)."""
	return sum(line["amount"] for line in actual_cost(station)["lines"] if line["source"] == "commission")


class TestReferrerCommission(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_accounts(COMPANY)
		cls.admin = make_user("sp.rc.admin@example.com", ("admin",))
		cls.partner = referrer()

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		if frappe.utils.get_assets_json() is None:  # CI builds no assets; the PDF only needs the HTML
			from unittest.mock import patch

			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		set_setting(account_map=[], referrer_commission_event=cm.DEPOSIT)
		cm.seed_account_map(COMPANY)

	def deal(self, with_referrer=True):
		"""An Agri Bank quote with a hidden 10,000 commission line, approved; the deposit comes next."""
		quote = make_quotation(rate=100000, valid_days=3, save=False)
		quote.append("items", {"sp_line_kind": COMMISSION, "qty": 1, "rate": COMMISSION_AMOUNT})
		quote.insert()
		quote.submit()
		approve_version(quote.name)
		self.quote = quote
		return quote

	def deposit(self, quote, set_referrer=True):
		"""The confirmed deposit makes the contract and the station; the referrer is set on the
		station (owner, 2026-11-21), then the deposit automation runs."""
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": COMPANY,
				"party_type": "Customer",
				"party": quote.party_name,
				"paid_from": "_Test Receivable - _TC",
				"paid_to": "_Test Cash - _TC",
				"paid_amount": 30000,
				"received_amount": 30000,
				"reference_no": "SP177",
				"reference_date": today(),
				"sp_is_deposit": 1,
				"sp_case": quote.sp_case,
			}
		)
		pe.insert()
		with self.patch_enqueue():
			pe.submit()
		so = frappe.db.get_value("Sales Order", {"sp_case": quote.sp_case, "docstatus": 1})
		station = frappe.get_doc(STATION, frappe.db.get_value("Sales Order", so, "sp_station"))
		station.financing_type = AGRI_BANK if frappe.db.exists("SP List Value", AGRI_BANK) else None
		if set_referrer:
			station.sales_partner = self.partner
		station.save()
		result = run_deposit(pe.name)
		return frappe.get_doc(STATION, station.name), result

	def patch_enqueue(self):
		from unittest.mock import patch

		return patch("frappe.enqueue")  # the deposit automation runs once the referrer is set

	def balance(self):
		from erpnext.accounts.utils import get_balance_on

		return -flt(get_balance_on(party_type="Sales Partner", party=self.partner, company=COMPANY))

	def test_a_10000_commission_is_in_the_cost_hidden_on_paper_and_owed_after_posting(self):
		quote = self.deal()
		before = self.balance()
		station, result = self.deposit(quote)
		self.assertEqual(flt(station.commission_amount), COMMISSION_AMOUNT)
		self.assertEqual(commission_cost(station.name), COMMISSION_AMOUNT)  # the station cost
		html = frappe.get_print("Quotation", quote.name, "SP Quotation", doc=quote)
		self.assertNotIn("10,000", html)  # the customer PDF does not show it
		self.assertTrue(result["referrer_commission"])
		self.assertEqual(self.balance() - before, COMMISSION_AMOUNT)  # owed to the referrer
		je = frappe.get_doc("Journal Entry", result["referrer_commission"])
		expense = next(a for a in je.accounts if flt(a.debit_in_account_currency))
		self.assertEqual((expense.project, je.sp_posting_event), (station.project, cm.EVENT))
		self.assertEqual(commission_cost(station.name), COMMISSION_AMOUNT)  # not counted twice
		self.assertEqual(
			frappe.db.get_value("Sales Order", station.sales_order, "sales_partner"), self.partner
		)

	def test_it_posts_once_and_the_referrer_is_paid_by_a_payment_entry(self):
		station, _result = self.deposit(self.deal())
		self.assertIsNone(cm.at(cm.DEPOSIT, station.name))  # once
		before = self.balance()
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Pay",
				"company": COMPANY,
				"party_type": "Sales Partner",
				"party": self.partner,
				"paid_from": "_Test Cash - _TC",
				"paid_amount": 4000,
				"received_amount": 4000,
				"reference_no": "SP177-PAY",
				"reference_date": today(),
			}
		)
		pe.setup_party_account_field()
		pe.set_missing_values()
		pe.paid_to = frappe.db.get_value("Account", {"company": COMPANY, "account_name": cm.PAYABLE_ACCOUNT})
		pe.insert()
		pe.submit()
		self.assertEqual(before - self.balance(), 4000)
		[row] = [r for r in cm.referrers({"referrer": self.partner})]
		self.assertEqual(
			(flt(row["paid"]) >= 4000, flt(row["balance"]), row["stations"] >= 1),
			(True, flt(row["posted"]) - flt(row["paid"]), True),
		)

	def test_no_referrer_waits_with_a_task_and_manual_posts_on_the_button(self):
		station, result = self.deposit(self.deal(), set_referrer=False)
		self.assertIsNone(result["referrer_commission"])
		ask = {"reference_doctype": STATION, "reference_name": station.name, "task_type": cm.REFERRER_TASK}
		self.assertTrue(frappe.db.exists("SP Task", {**ask, "status": "Open"}))
		set_setting(referrer_commission_event=cm.MANUAL)
		station.sales_partner = self.partner
		station.save()
		frappe.set_user(self.admin)
		name = cm.post_commission(station.name)
		frappe.set_user("Administrator")
		self.assertEqual(cm.posted(station.name), name)
		self.assertFalse(frappe.db.exists("SP Task", {**ask, "status": "Open"}))  # closed by the posting
		with self.assertRaises(frappe.ValidationError):
			cm.post_commission(station.name)  # already posted

	def test_a_referrer_without_a_mobile_is_refused_on_the_station(self):
		station, _result = self.deposit(self.deal(), set_referrer=False)
		bare = frappe.get_doc(
			{
				"doctype": "Sales Partner",
				"partner_name": "وسيط بلا موبايل",
				"commission_rate": 0,
				"territory": frappe.db.get_value("Territory", {"is_group": 0}) or "All Territories",
			}
		).insert()  # ERPNext's own records come without one, so the field is not required
		station.sales_partner = bare.name
		with self.assertRaises(frappe.MandatoryError):
			station.save()

	def test_only_the_admin_posts_and_the_mobile_is_unique(self):
		station, _result = self.deposit(self.deal(), set_referrer=False)
		manager = make_user("sp.rc.pm@example.com", ("project_manager",))
		frappe.set_user(manager)
		with self.assertRaises(frappe.PermissionError):
			cm.post_commission(station.name)
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.UniqueValidationError):
			frappe.get_doc(
				{
					"doctype": "Sales Partner",
					"partner_name": "مندوب آخر",
					"sp_mobile": frappe.db.get_value("Sales Partner", self.partner, "sp_mobile"),
					"commission_rate": 0,
					"territory": frappe.db.get_value("Territory", {"is_group": 0}) or "All Territories",
				}
			).insert()
