"""S2 site task board and TK1 my site tasks (SP-100): the planner gives the crew a task; the
technician checks in on site, logs the hours and marks it done; the board follows."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from smart_power.sp_site import site_tasks as st
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


class TestSiteTasks(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.amira = make_user("sp.tk.amira@example.com", ("project_manager",))
		cls.gaber = make_user("sp.tk.gaber@example.com", ("installation_technician",))
		cls.other = make_user("sp.tk.other@example.com", ("installation_technician",))
		cls.station = (
			frappe.get_doc({"doctype": "SP Station", "customer": "_Test Customer", "company": COMPANY})
			.insert()
			.name
		)

	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")

	def planned(self, title="تركيب الهياكل"):
		frappe.set_user(self.amira)
		task = st.plan(self.station, title, [self.gaber], str(add_days(today(), 1)))
		frappe.set_user("Administrator")
		return task

	def test_the_planner_gives_the_technician_a_task_he_sees(self):
		task = self.planned()
		doc = frappe.get_doc("Task", task)
		self.assertEqual(
			(doc.sp_station, doc.project),
			(self.station, frappe.db.get_value("SP Station", self.station, "project")),
		)
		frappe.set_user(self.gaber)
		mine = st.my_tasks()
		self.assertIn((task, "To do"), [(t["name"], t["column"]) for t in mine])
		self.assertRaises(frappe.PermissionError, st.plan, self.station, "x", [self.gaber])
		frappe.set_user(self.other)
		self.assertEqual(st.my_tasks(), [])  # nothing is his

	def test_the_planner_picks_from_the_installation_crew_only(self):
		frappe.set_user(self.amira)
		crew = {row["value"] for row in st.technicians()}
		self.assertLessEqual({self.gaber, self.other}, crew)
		self.assertNotIn(self.amira, crew)  # a planner without a crew role is not offered
		self.assertEqual([r["value"] for r in st.technicians("sp.tk.gaber")], [self.gaber])
		frappe.set_user(self.gaber)
		self.assertRaises(frappe.PermissionError, st.technicians)

	def test_check_in_records_the_time_and_the_location(self):
		task = self.planned("تمديد الكابلات")
		frappe.set_user(self.other)
		self.assertRaises(frappe.PermissionError, st.check_in, task, 28.1, 30.75)
		frappe.set_user(self.gaber)
		result = st.check_in(task, 28.1, 30.75)
		self.assertEqual(result["checkin_geo"], "28.1,30.75")
		self.assertTrue(result["checkin_at"])
		self.assertEqual(frappe.db.get_value("Task", task, "status"), st.WORKING)

	def test_done_with_photos_shows_in_the_boards_done_column(self):
		task = self.planned("تركيب الألواح")
		frappe.set_user(self.gaber)
		st.check_in(task)  # no GPS fix: it still checks in
		self.assertEqual(st.mark_done(task, 6), st.COMPLETED)
		frappe.set_user("Administrator")
		for n in (1, 2):
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"sp100-{n}.txt",
					"content": f"photo {n}",
					"attached_to_doctype": "Task",
					"attached_to_name": task,
				}
			).insert()
		row = next(r for r in st.board(self.station) if r["name"] == task)
		self.assertEqual((row["column"], row["hours"], row["photos"]), ("Done", 6, 2))
		self.assertIn("sp.tk.gaber", row["technicians"])
		frappe.set_user(self.gaber)
		self.assertNotIn(task, [t["name"] for t in st.my_tasks()])
		self.assertRaises(frappe.ValidationError, st.check_in, task)
