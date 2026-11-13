"""First version, option, quote creator and design inputs on a case's quote (SP-54)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.quotation import new_version
from smart_power.tests.test_quotation_case import case_for_test_customer, quote_for
from smart_power.tests.utils import make_quotation, make_user


class TestQuotationFields(IntegrationTestCase):
	def test_every_version_shares_the_first_version(self):
		v1 = quote_for(case_for_test_customer())
		v1.reload()
		self.assertEqual(v1.sp_root, v1.name)
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		v3 = frappe.get_doc("Quotation", new_version(v2.name))
		self.assertEqual({v2.sp_root, v3.sp_root}, {v1.name})

	def test_option_label_carries_to_new_versions(self):
		v1 = quote_for(case_for_test_customer())
		frappe.db.set_value("Quotation", v1.name, "sp_option_label", "B")
		v2 = frappe.get_doc("Quotation", new_version(v1.name))
		self.assertEqual(v2.sp_option_label, "B")

	def test_quote_creator_comes_from_the_case(self):
		aya = make_user("sp.qfields.aya@example.com", ("quote_creator",))
		q = quote_for(case_for_test_customer(quote_creator=aya))
		self.assertEqual(q.sp_quote_creator, aya)

	def test_design_inputs_are_kept(self):
		case = case_for_test_customer()
		q = make_quotation(save=False)
		q.sp_case = case.name
		q.sp_design_inputs = {"well_depth_m": 120, "motor_hp": 20}
		q.insert()
		q.reload()
		self.assertEqual(frappe.parse_json(q.sp_design_inputs), {"well_depth_m": 120, "motor_hp": 20})
