"""Employees and daily workers (SP-33): daily wage, skill, active-only pickers."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from smart_power.sp_core import workers
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


def worker(name: str, wage: float = 350, **kw):
	"""A daily worker: name, mobile, wage and skill only (no birth date or gender)."""
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": name,
			"company": COMPANY,
			"sp_is_daily_worker": 1,
			"sp_daily_wage": wage,
			"sp_skill": "Worker Skill-HELPER",
			"cell_number": "01001112233",
			**kw,
		}
	).insert()


class TestWorkers(IntegrationTestCase):
	def setUp(self):
		self.mostafa = make_user("sp.wk.mostafa@example.com", ("installation_manager",))
		self.cashier = make_user("sp.wk.cashier@example.com", ("showroom_cashier",))

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_new_line_starts_with_the_workers_wage(self):
		ahmed = worker("أحمد علي", 350)
		frappe.set_user(self.mostafa)
		line = workers.crew_line(ahmed.name)
		self.assertEqual(
			(line["employee_name"], flt(line["wage"]), line["skill"]),
			("أحمد علي", 350, "Worker Skill-HELPER"),
		)

	def test_a_deactivated_worker_leaves_the_pickers_but_keeps_his_old_lines(self):
		ahmed = worker("أحمد علي النشط", 350)
		frappe.set_user(self.mostafa)
		found = lambda: [r[0] for r in workers.worker_query("Employee", "أحمد علي النشط", "name", 0, 20, {})]  # noqa: E731
		self.assertIn(ahmed.name, found())
		frappe.set_user("Administrator")
		frappe.db.set_value("Employee", ahmed.name, "status", "Inactive")
		frappe.set_user(self.mostafa)
		self.assertNotIn(ahmed.name, found())
		self.assertNotIn(ahmed.name, [w.name for w in workers.workers_bundle()])
		line = workers.crew_line(ahmed.name)  # an old line still shows him
		self.assertEqual((line["employee_name"], line["active"]), ("أحمد علي النشط", False))

	def test_a_daily_worker_needs_a_wage_and_no_login(self):
		with self.assertRaises(frappe.ValidationError):
			worker("بدون أجر", 0)
		with self.assertRaises(frappe.ValidationError):
			worker("له حساب", 300, user_id=self.mostafa)

	def test_only_crew_roles_pick_crew(self):
		ahmed = worker("عامل", 300)
		frappe.set_user(self.cashier)
		with self.assertRaises(frappe.PermissionError):
			workers.crew_line(ahmed.name)
