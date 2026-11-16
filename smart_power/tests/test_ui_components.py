"""Shared form components (SP-44): edit with reason, rule banner, pickers, the line grid."""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power import audit
from smart_power.sp_finance.customer_payment import confirm
from smart_power.tests.test_customer_payment import PHOTO, account
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestEditWithReason(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from smart_power.sp_stock import warehouses as wh

		wh.seed_warehouses(COMPANY)

	def setUp(self):
		from smart_power.sp_sales.quotation import approve_version
		from smart_power.sp_stations.contract import ensure_contract

		set_setting(large_payment_threshold=100000)
		self.admin = make_user("sp.ui.admin@example.com", ("admin",))
		self.collector = make_user("sp.ui.collector@example.com", ("collection_officer",))
		self.instapay = account("SP InstaPay", "Bank", "Official", account_type="Bank")
		q = make_quotation(rate=200000, valid_days=3)
		q.submit()
		approve_version(q.name)
		result = ensure_contract(q.sp_case)
		frappe.get_doc("Sales Order", result["sales_order"]).submit()
		self.station = result["station"]

	def tearDown(self):
		frappe.set_user("Administrator")

	def confirmed_payment(self, amount=25000):
		frappe.set_user(self.collector)
		doc = frappe.get_doc(
			{
				"doctype": "SP Customer Payment",
				"station": self.station,
				"amount": amount,
				"method": "Payment Method-INSTAPAY",
				"receiving_account": self.instapay,
				"reference_no": "REF",
				"receipt_photo": PHOTO,
			}
		).insert()
		doc.submit()
		frappe.set_user(self.admin)
		confirm(doc.name)
		frappe.set_user("Administrator")
		return frappe.get_doc("SP Customer Payment", doc.name)

	def edit(self, user, doc, value, reason):
		frappe.set_user(user)
		try:
			return audit.edit_field(doc.doctype, doc.name, "amount", value, reason)
		finally:
			frappe.set_user("Administrator")

	def test_a_confirmed_amount_changes_only_with_a_reason_and_is_logged_and_reposted(self):
		doc = self.confirmed_payment(25000)
		old_entry = doc.payment_entry
		with self.assertRaises(frappe.ValidationError):
			self.edit(self.admin, doc, 24000, "")  # the reason is mandatory
		self.edit(self.admin, doc, 24000, "خطأ في كتابة المبلغ")
		doc.reload()
		self.assertEqual(flt(doc.amount), 24000)
		# the entry is reversed and posted again for the new amount
		self.assertEqual(frappe.db.get_value("Payment Entry", old_entry, "docstatus"), 2)
		self.assertEqual(flt(frappe.db.get_value("Payment Entry", doc.payment_entry, "paid_amount")), 24000)
		# Version (History) and the Edit Reason Log both have old → new
		version = frappe.get_all(
			"Version",
			{"ref_doctype": doc.doctype, "docname": doc.name},
			["data"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(json.loads(version.data)["changed"][0][1:], [25000, 24000])
		log = frappe.get_all(
			"SP Edit Reason Log",
			{"reference_name": doc.name, "fieldname": "amount"},
			["old_value", "new_value", "reason"],
		)[0]
		self.assertEqual(
			(flt(log.old_value), flt(log.new_value), log.reason), (25000, 24000, "خطأ في كتابة المبلغ")
		)
		self.assertTrue(frappe.db.exists("SP Review Item", {"reference_name": doc.name, "category": "Edit"}))

	def test_only_the_registered_roles_change_a_field(self):
		doc = self.confirmed_payment(25000)
		with self.assertRaises(frappe.PermissionError):
			self.edit(self.collector, doc, 24000, "سبب")
		frappe.set_user(self.collector)
		self.assertEqual(audit.editable_fields(doc.doctype, doc.name), [])
		frappe.set_user("Administrator")


class TestRuleBannerAndConfirm(IntegrationTestCase):
	def setUp(self):
		from smart_power.tests.utils import set_rule

		set_setting(validity_days=3, max_validity_days=0)
		set_rule("quote_validity", "Block")
		self.creator = make_user("sp.ui.creator@example.com", ("quote_creator",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_rule_at_block_names_itself_and_cannot_be_overridden_by_a_user(self):
		from smart_power.rules import check

		q = make_quotation(valid_days=10, save=False)  # longer than the 3 days allowed
		frappe.set_user(self.creator)
		result = check(q.as_dict())
		frappe.set_user("Administrator")
		blocked = [h for h in result["hits"] if h["level"] == "Block"]
		self.assertEqual([h["rule"] for h in blocked], ["quote_validity"])
		self.assertTrue(blocked[0]["title"])  # the banner names the rule
		self.assertFalse(result["can_override"])  # so the form's primary button is off
		ok = check(make_quotation(valid_days=3, save=False).as_dict())
		self.assertFalse([h for h in ok["hits"] if h["rule"] == "quote_validity"])

	def test_the_forms_with_rules_are_known_to_the_desk(self):
		from smart_power.rules import rule_doctypes

		self.assertTrue({"Quotation", "SP Case", "SP Transfer"} <= set(rule_doctypes()))
