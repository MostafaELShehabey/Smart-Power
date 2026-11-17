"""Marketing campaigns (SP-52): the funnel counts, spend from custody, who sees which."""

import itertools

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, today

from smart_power.sp_sales import campaigns
from smart_power.sp_sales.quotation import approve_version
from smart_power.tests import test_custody
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_test_case, make_user

load_erpnext_test_data()

EXHIBITION = "Lead Source-EXHIBITION"


def make_campaign(name="معرض صحارى", owner=None, **kw):
	return frappe.get_doc(
		{
			"doctype": "SP Campaign",
			"campaign_name": name,
			"channel": EXHIBITION,
			"start_date": today(),
			"owner_user": owner,
			**kw,
		}
	).insert()


MOBILES = itertools.count(1)


def lead(campaign, n):
	# a lead needs its own mobile (SP-51)
	mobile = f"0106{next(MOBILES):07d}"
	return frappe.get_doc(
		{"doctype": "Lead", "lead_name": f"عميل معرض {n}", "sp_campaign": campaign, "sp_mobile": mobile}
	).insert(ignore_permissions=True)


class TestCampaignResults(IntegrationTestCase):
	def test_funnel_counts_show_on_the_list(self):
		# معرض صحارى: 40 leads, 12 quotes, 3 won worth 1.2 M
		campaign = make_campaign().name
		for n in range(40):
			lead(campaign, n)
		won = []
		for n in range(12):
			case = make_test_case()
			frappe.db.set_value("SP Case", case, "campaign", campaign)
			q = make_quotation(case=case, rate=400000 if n < 3 else 1000)
			q.submit()
			if n < 3:
				approve_version(q.name)
				won.append(case)
		for case in won:
			doc = frappe.get_doc("SP Case", case)
			doc.db_set("status", "Won")
		campaigns.refresh(campaign)
		row = frappe.get_list(
			"SP Campaign",
			filters={"name": campaign},
			fields=["lead_count", "quote_count", "won_count", "contracted_value"],
		)[0]
		self.assertEqual((row.lead_count, row.quote_count, row.won_count), (40, 12, 3))
		self.assertEqual(flt(row.contracted_value), 1200000)

	def test_a_lead_and_a_sent_quote_count_at_once(self):
		campaign = make_campaign("حملة فيسبوك").name
		lead(campaign, 1)
		self.assertEqual(frappe.db.get_value("SP Campaign", campaign, "lead_count"), 1)
		case = make_test_case()
		case_doc = frappe.get_doc("SP Case", case)
		case_doc.campaign = campaign
		case_doc.save()
		make_quotation(case=case).submit()
		self.assertEqual(frappe.db.get_value("SP Campaign", campaign, "quote_count"), 1)

	def test_dates_and_channel_are_checked(self):
		with self.assertRaises(frappe.ValidationError):
			make_campaign("حملة", end_date=add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			make_campaign("حملة", channel="Lost Reason-PRICE_CHECK_ONLY")

	def test_a_marketing_agent_sees_her_own_campaigns(self):
		maha = make_user("sp.cmp.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator"))
		other = make_user("sp.cmp.other@example.com", ("marketing_agent",))
		mine = make_campaign("حملة مها", owner=maha).name
		theirs = make_campaign("حملة أخرى", owner=other).name
		frappe.set_user(maha)
		try:
			seen = set(frappe.get_list("SP Campaign", filters={"name": ("in", [mine, theirs])}, pluck="name"))
			self.assertEqual(seen, {mine})
			self.assertFalse(frappe.has_permission("SP Campaign", "read", theirs))
		finally:
			frappe.set_user("Administrator")


class TestCampaignSpend(IntegrationTestCase):
	"""A spend recorded from the agent's custody counts once the admin approves her settlement."""

	@classmethod
	def setUpClass(cls):
		# its own (a borrowed classmethod stays bound to TestCustody, and this class would then
		# never get its own rollback)
		super().setUpClass()
		test_custody.wh.seed_warehouses(test_custody.COMPANY)
		test_custody.seed_accounts(test_custody.COMPANY)

	setUp = test_custody.TestCustody.setUp
	tearDown = test_custody.TestCustody.tearDown
	make_station = test_custody.TestCustody.make_station
	give = test_custody.TestCustody.give
	settle = test_custody.TestCustody.settle
	approve = test_custody.TestCustody.approve

	def test_spend_counts_after_the_settlement_is_approved(self):
		maha = make_user("sp.cmp.spend@example.com", ("marketing_agent", "custody_holder"))
		self.doc = self.give(maha, 5000)
		self.mostafa = maha  # settle() acts as the holder
		campaign = make_campaign("معرض صحارى", owner=maha).name
		frappe.set_user(maha)
		try:
			from smart_power.sp_finance import custody

			opts = campaigns.spend_options(campaign)
			self.assertEqual(opts["expense_type"], "Expense Type-MARKETING")
			custody.add_expense(
				self.doc.name,
				{
					"amount": 2000,
					"expense_type": opts["expense_type"],
					"center_type": "Center",
					"cost_center": opts["custodies"][0].cost_center,
					"receipt_photo": test_custody.PHOTO,
					"campaign": campaign,
				},
			)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(flt(frappe.db.get_value("SP Campaign", campaign, "spend_total")), 0)
		self.approve(self.settle())
		self.assertEqual(flt(frappe.db.get_value("SP Campaign", campaign, "spend_total")), 2000)


class TestCampaignOnRequest(IntegrationTestCase):
	def test_quote_request_carries_the_campaign(self):
		from smart_power.sp_sales.quote_request import create_quote_request

		campaign = make_campaign("حملة البنك", channel="Lead Source-BANK").name
		r = create_quote_request(
			{
				"system_type": "System Type-ONGRID",
				"mobile": "01005205201",
				"customer_name": "عميل من البنك",
				"channel": "Call",
				"campaign": campaign,
				"details": {"kw": 10},
			}
		)
		self.assertEqual(frappe.db.get_value("SP Case", r["case"], "campaign"), campaign)
