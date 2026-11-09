"""Customer master: mobile and duplicate check (SP-31)."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_sales.customer import find_by_mobile, normalize_mobile


def make_customer(mobile="01001234567", name="عميل تجربة", **kw):
	return frappe.get_doc({"doctype": "Customer", "customer_name": name, "sp_mobile": mobile, **kw}).insert()


class TestCustomerMobile(IntegrationTestCase):
	def test_normalize(self):
		for raw in ("01001234567", "+20 100 123 4567", "00201001234567", "0100-123-4567"):
			self.assertEqual(normalize_mobile(raw), "01001234567", raw)

	def test_mobile_is_stored_clean(self):
		doc = make_customer("+20 111 222 3333")
		self.assertEqual(doc.sp_mobile, "01112223333")
		self.assertEqual(find_by_mobile("01112223333"), doc.name)

	def test_mobile_is_required(self):
		with self.assertRaises(frappe.MandatoryError):
			make_customer(mobile=None)

	def test_invalid_mobile_is_refused(self):
		for bad in ("1234", "01301234567", "0100123456"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				make_customer(bad)

	def test_invalid_second_mobile_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_customer("01001230000", sp_mobile_2="999")

	def test_duplicate_mobile_is_refused_with_a_link(self):
		first = make_customer("01551234567")
		with self.assertRaises(frappe.DuplicateEntryError) as ctx:
			make_customer("+201551234567", name="عميل مكرر")
		self.assertIn(first.name, str(ctx.exception))

	def test_saving_the_same_customer_again_is_fine(self):
		doc = make_customer("01223334444")
		doc.customer_name = "اسم جديد"
		doc.save()


class TestCustomerTierRegion(IntegrationTestCase):
	def test_tier_sets_customer_type(self):
		doc = make_customer("01009990001", sp_tier="Company")
		self.assertEqual(doc.customer_type, "Company")
		doc.sp_tier = "Individual"
		doc.save()
		self.assertEqual(doc.customer_type, "Individual")

	def test_default_tier_is_individual(self):
		doc = make_customer("01009990002")
		self.assertEqual((doc.sp_tier, doc.customer_type), ("Individual", "Individual"))

	def test_region_from_the_region_list(self):
		region = frappe.get_doc(
			{"doctype": "SP List Value", "list_name": "Region", "code": "DAKHLA_T", "value_ar": "الداخلة"}
		).insert()
		doc = make_customer("01009990003", sp_region=region.name)
		self.assertEqual(doc.sp_region, "Region-DAKHLA_T")

	def test_value_from_another_list_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_customer("01009990004", sp_region="System Type-PUMP")


class TestFeaturedCustomer(IntegrationTestCase):
	def test_mark_featured_once(self):
		from smart_power.sp_sales.customer import mark_featured

		doc = make_customer("01009990010")
		self.assertFalse(doc.sp_featured)
		self.assertTrue(mark_featured(doc.name))
		self.assertFalse(mark_featured(doc.name))
		self.assertEqual(frappe.db.get_value("Customer", doc.name, "sp_featured"), 1)

	def test_featured_is_read_only_on_the_form(self):
		field = frappe.get_meta("Customer").get_field("sp_featured")
		self.assertTrue(field.read_only)

	def test_follow_up_owner_links_to_a_user(self):
		doc = make_customer("01009990011", sp_owner_user="Administrator")
		self.assertEqual(doc.sp_owner_user, "Administrator")

	def test_list_star_is_hooked(self):
		self.assertIn("public/js/customer_list.js", frappe.get_hooks("doctype_list_js")["Customer"])
