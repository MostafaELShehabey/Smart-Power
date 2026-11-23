"""X3 Fields and forms (SP-132): the quote request's questions per system type, custom fields on
the forms with "show only when", hiding that keeps the data, reordering; the admin only."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core import form_designer as fd
from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_sales.quote_request import clean_details, get_request_fields
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

IRRIGATION, PUMP = "System Type-IRRIGATION", "System Type-PUMP"
SOIL, FORM = "Soil Type", "SP Field Entry"


class TestRequestQuestions(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_list_values()
		cls.admin = make_user("sp.fd.admin@example.com", ("admin",))
		cls.intake = make_user("sp.fd.intake@example.com", ("lead_intake",))

	def setUp(self):
		frappe.set_user(self.admin)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_a_required_soil_list_for_irrigation_only(self):
		fd.new_list(SOIL, "نوع التربة")
		self.assertEqual(
			frappe.db.get_value("Translation", {"language": "ar", "source_text": SOIL}, "translated_text"),
			"نوع التربة",
		)
		self.assertRaises(frappe.ValidationError, fd.new_list, SOIL)  # once
		for code, value in (("CLAY", "طينية"), ("SAND", "رملية")):
			frappe.get_doc(
				{"doctype": fd.LIST_VALUE, "list_name": SOIL, "code": code, "value_ar": value}
			).insert()
		fd.request_add(
			IRRIGATION,
			{"label": "نوع التربة", "label_en": "Soil Type", "kind": "list", "list": SOIL, "reqd": 1},
		)
		frappe.set_user(self.intake)
		field = next(f for f in get_request_fields(IRRIGATION) if f["fieldname"] == "soil_type")
		self.assertEqual(
			(field["fieldtype"], set(field["options"].split("\n"))), ("Select", {"طينية", "رملية"})
		)
		# the type's other required answers, so only the soil decides
		others = {
			f["fieldname"]: 1 if f["fieldtype"] in ("Float", "Int", "Check") else "x"
			for f in get_request_fields(IRRIGATION)
			if f.get("reqd") and f["fieldname"] != "soil_type" and f["fieldtype"] != "Load Table"
		}
		with self.assertRaises(frappe.MandatoryError) as missing:
			clean_details(IRRIGATION, others)
		self.assertIn("Soil Type", str(missing.exception))
		self.assertEqual(clean_details(IRRIGATION, {**others, "soil_type": "رملية"})["soil_type"], "رملية")
		self.assertRaises(frappe.ValidationError, clean_details, IRRIGATION, {**others, "soil_type": "صخرية"})
		self.assertNotIn("soil_type", [f["fieldname"] for f in get_request_fields(PUMP)])  # hidden for pumps
		frappe.set_user(self.admin)
		frappe.get_doc(
			{"doctype": fd.LIST_VALUE, "list_name": SOIL, "code": "ROCK", "value_ar": "صخرية"}
		).insert()
		self.assertIn(
			"صخرية",
			next(f for f in get_request_fields(IRRIGATION) if f["fieldname"] == "soil_type")["options"],
		)

	def test_a_question_moves_and_is_removed(self):
		fd.request_add(PUMP, {"label": "مصدر الكهرباء", "label_en": "Power Source", "kind": "text"})
		names = [f["fieldname"] for f in fd.request_load(PUMP)["fields"]]
		moved = fd.request_change(PUMP, "power_source", {"move": "up"})
		self.assertEqual(
			[f["fieldname"] for f in moved["fields"]].index("power_source"), names.index("power_source") - 1
		)
		gone = fd.request_change(PUMP, "power_source", {"remove": 1})
		self.assertNotIn("power_source", [f["fieldname"] for f in gone["fields"]])

	def test_the_admin_only(self):
		frappe.set_user(self.intake)
		self.assertRaises(frappe.PermissionError, fd.forms)
		self.assertRaises(frappe.PermissionError, fd.request_add, PUMP, {"label": "x", "kind": "text"})


class TestFormFields(IntegrationTestCase):
	"""Custom fields change the table (DDL), so this class removes what it made."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from smart_power.sp_core.permissions_matrix import seed_module_map

		seed_module_map()
		cls.admin = make_user("sp.fd.admin@example.com", ("admin",))

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Custom Field", {"dt": FORM, "fieldname": ("like", "cx_%")}, pluck="name"):
			fieldname = frappe.db.get_value("Custom Field", name, "fieldname")
			frappe.delete_doc("Custom Field", name, force=True)
			if frappe.db.has_column(FORM, fieldname):
				frappe.db.sql_ddl(f"alter table `tab{FORM}` drop column `{fieldname}`")  # nosemgrep
		frappe.db.delete("Property Setter", {"doc_type": FORM, "field_name": ("like", "cx_%")})
		frappe.db.delete("Property Setter", {"doc_type": FORM, "property": "field_order"})
		frappe.db.delete(fd.RULE, {"document_type": FORM})
		frappe.db.delete("SP Audit Log", {"reference_name": FORM, "action": ("like", "Form field%")})
		frappe.db.commit()
		frappe.clear_cache(doctype=FORM)
		fd.clear_rules()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user(self.admin)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_only_the_business_forms_open(self):
		forms = {f["doctype"] for f in fd.forms()["forms"]}
		self.assertIn(FORM, forms)
		self.assertNotIn("User", forms)
		self.assertRaises(frappe.ValidationError, fd.load, "User")

	def test_a_field_shown_and_required_only_for_one_entry_kind(self):
		entry_kind = next(c for c in fd.load(FORM)["conditions"] if c["fieldname"] == "entry_kind")
		value = entry_kind["options"][0]["value"]
		page = fd.add_field(
			FORM,
			{
				"label": "رقم العداد",
				"label_en": "Meter No",
				"kind": "text",
				"reqd": 1,
				"when": {"field": "entry_kind", "value": value},
				"after": "entry_kind",
			},
		)
		row = next(f for f in page["fields"] if f["fieldname"] == "cx_meter_no")
		self.assertEqual((row["custom"], row["when"]["value"]), (1, value))
		self.assertIn("=", row["when"]["text"])  # the field's label and the value, for the admin
		names = [f["fieldname"] for f in page["fields"]]
		self.assertEqual(names.index("cx_meter_no"), names.index("entry_kind") + 1)
		df = frappe.get_meta(FORM).get_field("cx_meter_no")
		self.assertIn("entry_kind", df.depends_on)
		doc = frappe.new_doc(FORM)
		doc.entry_kind = value
		self.assertRaises(frappe.MandatoryError, fd.validate_required, doc)  # checked on the server too
		doc.cx_meter_no = "A-12"
		fd.validate_required(doc)
		other = frappe.new_doc(FORM)
		other.entry_kind = entry_kind["options"][1]["value"]
		fd.validate_required(other)  # another entry type does not ask for it

	def test_hiding_a_field_keeps_it_and_moving_reorders(self):
		fd.add_field(FORM, {"label": "ملاحظة الموقع", "label_en": "Site Note", "kind": "long_text"})
		hidden = fd.change_field(FORM, "cx_site_note", {"hidden": 1})
		self.assertTrue(next(f for f in hidden["fields"] if f["fieldname"] == "cx_site_note")["hidden"])
		self.assertTrue(frappe.db.exists("Custom Field", {"dt": FORM, "fieldname": "cx_site_note"}))
		self.assertTrue(frappe.db.has_column(FORM, "cx_site_note"))  # the records keep their values
		before = [f["fieldname"] for f in hidden["fields"]]
		after = [f["fieldname"] for f in fd.change_field(FORM, "cx_site_note", {"move": "up"})["fields"]]
		self.assertEqual(after.index("cx_site_note"), before.index("cx_site_note") - 1)

	def test_a_list_field_links_to_the_list(self):
		fd.add_field(FORM, {"label": "المنطقة", "label_en": "Area", "kind": "list", "list": "Region"})
		df = frappe.get_meta(FORM).get_field("cx_area")
		self.assertEqual((df.fieldtype, df.options), ("Link", fd.LIST_VALUE))
		self.assertIn("Region", df.link_filters)
