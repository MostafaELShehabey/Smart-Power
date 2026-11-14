"""Document numbering (SP-134, X8): formats, counters and yearly reset."""

import frappe
from frappe.model.naming import NamingSeries
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate

from smart_power.sp_core.numbering import as_series, get_numbering, set_counter
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import make_user


def row(doctype, series=None):
	return next(
		r for r in get_numbering() if r["doctype"] == doctype and (series is None or r["series"] == series)
	)


def make_task(subject="مهمة"):
	return frappe.get_doc(
		{"doctype": "SP Task", "subject": subject, "task_type": "Other", "assigned_to": "Administrator"}
	).insert(ignore_permissions=True)


class TestNumbering(IntegrationTestCase):
	def test_format_names_become_dot_series(self):
		self.assertEqual(as_series("format:TASK-{YYYY}-{#####}"), "TASK-.YYYY.-.#####")
		self.assertEqual(as_series("CS-.YYYY.-.#####"), "CS-.YYYY.-.#####")
		self.assertIsNone(as_series("hash"))
		self.assertIsNone(as_series("field:rule_key"))

	def test_rows_show_this_years_prefix_and_next_number(self):
		year = nowdate()[:4]
		case = row("SP Case")
		self.assertEqual(case["prefix"], f"CS-{year}-")
		self.assertTrue(case["yearly"])
		self.assertEqual(case["next"], f"CS-{year}-{str(case['current'] + 1).zfill(5)}")
		quote = row("Quotation")
		self.assertTrue(quote["in_naming_settings"])
		self.assertEqual(len(quote["next"].removeprefix(quote["prefix"])), 5)  # Frappe's default digits

	def test_tasks_have_their_own_yearly_counter(self):
		year = nowdate()[:4]
		task = make_task()
		self.assertTrue(task.name.startswith(f"TASK-{year}-"))
		counter = NamingSeries("TASK-.YYYY.-.#####").get_current_value()
		self.assertEqual(int(task.name.rsplit("-", 1)[1]), counter)
		# a review item does not move the task counter
		frappe.get_doc(
			{"doctype": "SP Review Item", "reference_doctype": "SP Task", "reference_name": task.name}
		).insert(ignore_permissions=True, ignore_mandatory=True)
		self.assertEqual(NamingSeries("TASK-.YYYY.-.#####").get_current_value(), counter)

	def test_set_counter_needs_a_reason_and_is_audited(self):
		series = row("SP Case")["series"]
		used = int(make_case().name.rsplit("-", 1)[1])
		with self.assertRaises(frappe.ValidationError):
			set_counter("SP Case", series, used + 100, "  ")
		set_counter("SP Case", series, used + 100, "بداية دفتر جديد")
		self.assertEqual(row("SP Case")["current"], used + 100)
		self.assertTrue(
			frappe.db.exists("SP Audit Log", {"action": "Set naming counter", "reference_doctype": "SP Case"})
		)
		self.assertEqual(int(make_case().name.rsplit("-", 1)[1]), used + 101)

	def test_counter_never_goes_below_a_used_number(self):
		series = row("SP Case")["series"]
		used = int(make_case().name.rsplit("-", 1)[1])
		with self.assertRaises(frappe.ValidationError):
			set_counter("SP Case", series, used - 1, "خطأ")

	def test_only_the_admin(self):
		user = make_user("sp.numbering.sales@example.com", ("customer_followup",))
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_numbering()
		finally:
			frappe.set_user("Administrator")

	def test_unknown_series_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			set_counter("SP Case", "HACK-.#####", 5, "x")
