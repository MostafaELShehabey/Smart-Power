"""Q1 quotes list (SP-64): system, size and follow-up owner from the case, the latest version of
each quote, the creator's own quotes with margin, the follow-up view without cost."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales import quote_list
from smart_power.sp_sales.quotation import new_version
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_user

PUMP, ONGRID = "System Type-PUMP", "System Type-ONGRID"
COST_FIELDS = ("sp_total_cost", "sp_profit", "sp_margin_pct")
PUMP_REQUEST = {"hp": 20, "well_depth_m": 120, "water_level_m": 40, "pump_depth_m": 100}


class TestQuoteList(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.aya = make_user("sp.q1.aya@example.com", ("quote_creator",))
		cls.amira = make_user("sp.q1.amira@example.com", ("quote_creator",))
		cls.camelia = make_user("sp.q1.camelia@example.com", ("followup_all",))
		cls.owner = make_user("sp.q1.owner@example.com", ("lead_intake", "customer_followup"))

	def case(self, creator, system=PUMP, details=None):
		return case_for_test_customer(
			follow_up_owner=self.owner,
			quote_creator=creator,
			system_types=[{"system_type": system}],
			request_details=details if details is not None else PUMP_REQUEST,
		)

	def test_system_size_and_owner_come_from_the_case(self):
		case = self.case(self.aya)
		q = quote_for(case)
		self.assertEqual((q.sp_system_type, q.sp_size, q.sp_follow_up_owner), (PUMP, "20 HP", self.owner))
		other = make_user("sp.q1.owner2@example.com", ("lead_intake", "customer_followup"))
		from smart_power.sp_sales.case import reassign

		reassign(case.name, "follow_up_owner", other, "moved to the other branch")
		self.assertEqual(frappe.db.get_value("Quotation", q.name, "sp_follow_up_owner"), other)
		case.reload()
		case.request_details = {"kw": 15}
		case.set("system_types", [{"system_type": ONGRID}])
		case.save()
		row = frappe.db.get_value("Quotation", q.name, ["sp_follow_up_owner", "sp_system_type", "sp_size"])
		self.assertEqual(row, (other, ONGRID, "15 kW"))

	def test_only_the_latest_version_is_latest(self):
		v1 = quote_for(self.case(self.aya))
		v1.submit()
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		latest = lambda: {  # noqa: E731
			n: frappe.db.get_value("Quotation", n, "sp_is_latest") for n in (v1.name, v2.name)
		}
		self.assertEqual(latest(), {v1.name: 0, v2.name: 1})
		# the draft v2 is deleted: v1 is the latest again
		frappe.delete_doc("Quotation", v2.name)
		self.assertEqual(frappe.db.get_value("Quotation", v1.name, "sp_is_latest"), 1)
		# the next version takes over
		v3 = frappe.get_doc("Quotation", new_version(v1.name))
		v3.submit()
		self.assertEqual(frappe.db.get_value("Quotation", v1.name, "sp_is_latest"), 0)
		self.assertEqual(frappe.db.get_value("Quotation", v3.name, "sp_is_latest"), 1)

	def test_creator_sees_her_quotes_with_margin(self):
		mine = quote_for(self.case(self.aya))
		theirs = quote_for(self.case(self.amira))
		frappe.set_user(self.aya)
		try:
			rows = frappe.get_list(
				"Quotation",
				filters={"sp_quote_creator": self.aya, "sp_is_latest": 1},
				fields=["name", "sp_margin_pct"],
			)
			self.assertIn("sp_margin_pct", rows[0])
		finally:
			frappe.set_user("Administrator")
		names = [r.name for r in rows]
		self.assertIn(mine.name, names)
		self.assertNotIn(theirs.name, names)

	def test_follow_up_sees_all_quotes_without_cost(self):
		mine = quote_for(self.case(self.aya))
		theirs = quote_for(self.case(self.amira))
		meta = frappe.get_meta("Quotation")
		frappe.set_user(self.camelia)
		try:
			names = frappe.get_list("Quotation", filters={"sp_is_latest": 1}, pluck="name")
			# the export reads through reportview, which drops the fields of a permlevel she lacks
			from frappe.desk.reportview import get_form_params

			frappe.local.form_dict = frappe._dict(
				doctype="Quotation",
				fields=["`tabQuotation`.`name`", *(f"`tabQuotation`.`{f}`" for f in COST_FIELDS)],
				filters=[["Quotation", "sp_is_latest", "=", 1]],
			)
			fields = get_form_params()["fields"]
			readable = meta.get_permlevel_access("read")
		finally:
			frappe.set_user("Administrator")
		self.assertTrue({mine.name, theirs.name} <= set(names))
		for f in COST_FIELDS:
			self.assertNotIn(meta.get_field(f).permlevel, readable)
			self.assertFalse(any(f in field for field in fields), fields)

	def test_size_from_the_design_inputs_when_the_request_has_none(self):
		q = quote_for(self.case(self.aya, system=ONGRID, details={"kw": 0}))
		self.assertIsNone(q.sp_size)
		self.assertEqual(quote_list.size_of(None, '{"kw": 7.5}'), "7.5 kW")

	def test_backfill_marks_the_existing_quotes(self):
		v1 = quote_for(self.case(self.aya))
		v1.submit()
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		frappe.db.sql(
			"update tabQuotation set sp_is_latest = 0, sp_size = null where name in %s", [(v1.name, v2.name)]
		)
		quote_list.backfill()
		self.assertEqual(frappe.db.get_value("Quotation", v2.name, ["sp_is_latest", "sp_size"]), (1, "20 HP"))
		self.assertEqual(frappe.db.get_value("Quotation", v1.name, "sp_is_latest"), 0)
