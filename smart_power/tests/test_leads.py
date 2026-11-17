"""Marketing leads (SP-51): mobile and duplicates, my leads only, convert to a request."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime, today

from smart_power.sp_sales import campaigns, leads
from smart_power.sp_sales.quote_request import create_quote_request
from smart_power.tests.utils import load_erpnext_test_data, make_customer, make_user

load_erpnext_test_data()


def as_user(user, fn, *args, **kw):
	frappe.set_user(user)
	try:
		return fn(*args, **kw)
	finally:
		frappe.set_user("Administrator")


def new_lead(mobile, name="عميل محتمل", **kw):
	return frappe.get_doc({"doctype": "Lead", "lead_name": name, "sp_mobile": mobile, **kw}).insert()


class TestLeads(IntegrationTestCase):
	def setUp(self):
		self.maha = make_user("sp.ld.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator"))
		self.camelia = make_user(
			"sp.ld.camelia@example.com", ("lead_intake", "customer_followup", "followup_all")
		)
		self.other = make_user("sp.ld.other@example.com", ("marketing_agent",))

	def test_mobile_is_required_valid_and_unique(self):
		with self.assertRaises(frappe.MandatoryError):
			frappe.get_doc({"doctype": "Lead", "lead_name": "بلا رقم"}).insert()
		with self.assertRaises(frappe.ValidationError):
			new_lead("12345")
		lead = new_lead("01005100501")
		self.assertEqual((lead.sp_mobile, lead.mobile_no), ("01005100501", "01005100501"))
		with self.assertRaises(frappe.DuplicateEntryError):
			new_lead("01005100501")
		make_customer("01005100502", "عميل قائم")
		with self.assertRaises(frappe.DuplicateEntryError):
			new_lead("01005100502")  # already a customer

	def test_follow_up_owner_is_the_follow_up_lead_and_source_comes_from_the_campaign(self):
		campaign = frappe.get_doc(
			{
				"doctype": "SP Campaign",
				"campaign_name": "حملة",
				"channel": "Lead Source-BANK",
				"start_date": today(),
			}
		).insert()
		lead = new_lead("01005100503", sp_campaign=campaign.name)
		self.assertEqual(lead.sp_follow_up_owner, leads.followup_lead())
		self.assertEqual(lead.sp_source, "Lead Source-BANK")

	def test_maha_cannot_see_camelias_leads(self):
		hers = as_user(self.maha, new_lead, "01005100504", "عميل مها").name
		theirs = as_user(
			self.other, new_lead, "01005100505", "عميل غيرها", sp_follow_up_owner=self.other
		).name
		seen = as_user(
			self.maha, frappe.get_list, "Lead", filters={"name": ("in", [hers, theirs])}, pluck="name"
		)
		self.assertEqual(seen, [hers])
		self.assertFalse(frappe.has_permission("Lead", "read", theirs, user=self.maha))
		with self.assertRaises(frappe.PermissionError):
			as_user(self.maha, frappe.client.get, "Lead", theirs)  # not through the API either
		# the follow-up lead sees both
		both = as_user(
			self.camelia, frappe.get_list, "Lead", filters={"name": ("in", [hers, theirs])}, pluck="name"
		)
		self.assertEqual(set(both), {hers, theirs})

	def test_a_converted_lead_counts_as_won_in_its_campaign(self):
		campaign = frappe.get_doc(
			{
				"doctype": "SP Campaign",
				"campaign_name": "معرض",
				"channel": "Lead Source-EXHIBITION",
				"start_date": today(),
				"owner_user": self.maha,
			}
		).insert()
		lead = as_user(self.maha, new_lead, "01005100506", "زائر المعرض", sp_campaign=campaign.name)
		opts = as_user(self.maha, leads.convert_options, lead.name)
		self.assertEqual(
			(opts["channel"], opts["campaign"], opts["mobile"]), ("Marketing", campaign.name, "01005100506")
		)
		self.assertTrue(all(opts.values()))  # nothing empty travels to C3 (it would arrive as "null")
		r = as_user(
			self.maha,
			create_quote_request,
			{**opts, "system_type": "System Type-ONGRID", "details": {"kw": 10}},
		)
		lead.reload()
		self.assertEqual((lead.sp_case, lead.status), (r["case"], "Converted"))
		self.assertEqual(frappe.db.get_value("SP Case", r["case"], "campaign"), campaign.name)
		frappe.db.set_value("SP Case", r["case"], "status", "Won")
		campaigns.refresh(campaign.name)
		self.assertEqual(frappe.db.get_value("SP Campaign", campaign.name, "won_count"), 1)
		with self.assertRaises(frappe.ValidationError):
			leads.convert_options(lead.name)  # already a request

	def test_leads_waiting_more_than_a_day_are_counted(self):
		old = as_user(self.maha, new_lead, "01005100507", "عميل قديم")
		as_user(self.maha, new_lead, "01005100508", "عميل جديد")
		frappe.db.set_value("Lead", old.name, "creation", add_to_date(now_datetime(), hours=-25))
		self.assertEqual(leads.waiting_count(self.maha), 1)
