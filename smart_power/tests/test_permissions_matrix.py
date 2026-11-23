"""X2 Permissions matrix (SP-131): ticks become Frappe's Role Permissions; field and row rules;
clone a role; preview its menu; the admin's access never changes."""

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core import permissions_matrix as pm
from smart_power.sp_core import row_rules
from smart_power.sp_stock import po_print
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

PO, ASSISTANT = "Purchase Order", "SP Purchase Assistant"


def perms(role):
	"""A role's Custom DocPerm rows, without their names and the role itself."""
	keys = ("parent", "permlevel", "if_owner", "read", "write", "create", "delete", "submit", "export")
	return sorted(
		tuple(r[k] for k in keys) for r in frappe.get_all("Custom DocPerm", {"role": role}, list(keys))
	)


class TestPermissionsMatrix(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		pm.seed_module_map()
		cls.admin = make_user("sp.pm.admin@example.com", ("admin",))

	def setUp(self):
		frappe.set_user(self.admin)
		self.addCleanup(frappe.set_user, "Administrator")

	def user_with(self, email, role):
		user = make_user(email)
		frappe.get_doc("User", user).add_roles(role)
		return user

	def test_supplier_prices_ticked_for_a_new_role_show_the_rates(self):
		pm.new_role(ASSISTANT)
		self.assertTrue(frappe.db.get_value("Role", ASSISTANT, "is_custom"))
		self.assertRaises(  # a field rule needs the document first
			frappe.ValidationError, pm.save, ASSISTANT, {}, {"supplier_prices": True}
		)
		changes = pm.save(ASSISTANT, {PO: {"view": True}}, {"supplier_prices": True})
		self.assertIn("Purchase Order level 2: read → ✓", changes)
		user = self.user_with("sp.pm.assistant@example.com", ASSISTANT)
		frappe.set_user(user)
		self.assertTrue(frappe.has_permission(PO, "read"))
		self.assertIn(2, frappe.get_meta(PO).get_permlevel_access("read", user=user))
		self.assertTrue(po_print.sees_prices())
		frappe.set_user(self.admin)
		state = next(dt for m in pm.load(ASSISTANT)["modules"] for dt in m["doctypes"] if dt["doctype"] == PO)
		self.assertEqual((state["view"], state["create"]), (True, False))
		self.assertTrue(
			frappe.db.exists("SP Audit Log", {"action": "Permissions changed", "reference_name": ASSISTANT})
		)

	def test_a_matrix_role_opens_the_groups_it_may_read(self):
		pm.new_role("SP Purchase Viewer")
		pm.save("SP Purchase Viewer", {PO: {"view": True}})
		groups = {g["group"] for g in pm.preview("SP Purchase Viewer")["groups"]}
		self.assertIn("Purchasing", groups)
		self.assertNotIn("Finance", groups)

	def test_a_cloned_role_has_the_same_permissions(self):
		result = pm.clone("SP Customer Followup", "SP Followup 2")
		self.assertTrue(result["permissions"])
		self.assertEqual(perms("SP Followup 2"), perms("SP Customer Followup"))
		case_steps = {
			(t.state, t.action, t.next_state)
			for t in frappe.get_all(
				"Workflow Transition", {"allowed": "SP Customer Followup"}, ["state", "action", "next_state"]
			)
		}
		cloned_steps = {
			(t.state, t.action, t.next_state)
			for t in frappe.get_all(
				"Workflow Transition", {"allowed": "SP Followup 2"}, ["state", "action", "next_state"]
			)
		}
		self.assertEqual(cloned_steps, case_steps)

	def test_the_store_keepers_menu_preview(self):
		menu = {g["group"]: g["items"] for g in pm.preview("SP Main Store Keeper")["groups"]}
		self.assertLessEqual({"Smart Power", "Inventory"}, set(menu))
		self.assertIn("My Tasks", menu["Smart Power"])
		self.assertIn("Receive Goods", menu["Purchasing"])
		self.assertNotIn("Finance", menu)

	def test_the_admin_keeps_its_access(self):
		for role in ("SP Admin", "System Manager"):
			self.assertRaises(frappe.ValidationError, pm.save, role, {PO: {"view": False}})
		self.assertTrue(pm.load("SP Admin")["locked"])
		frappe.set_user(make_user("sp.pm.clerk@example.com", ("lead_intake",)))
		self.assertRaises(frappe.PermissionError, pm.load, "SP Lead Intake")

	def test_own_records_and_confirm_on_a_workflow(self):
		pm.new_role("SP Station Helper")
		pm.save(
			"SP Station Helper", {"SP Station": {"view": True, "edit": True, "own": True, "confirm": pm.ALL}}
		)
		row = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": "SP Station", "role": "SP Station Helper", "permlevel": 0},
			["if_owner", "write"],
			as_dict=True,
		)
		self.assertEqual((row.if_owner, row.write), (1, 1))
		workflow = frappe.get_doc("Workflow", {"document_type": "SP Station", "is_active": 1})
		steps = {(t.state, t.action, t.next_state) for t in workflow.transitions}
		mine = {
			(t.state, t.action, t.next_state)
			for t in workflow.transitions
			if t.allowed == "SP Station Helper"
		}
		self.assertEqual(mine, steps)
		pm.save("SP Station Helper", {"SP Station": {"confirm": pm.NONE}})
		self.assertFalse(frappe.db.exists("Workflow Transition", {"allowed": "SP Station Helper"}))

	def test_assigned_to_me_limits_the_tasks_a_role_reads(self):
		pm.new_role("SP Task Reader")
		pm.save("SP Task Reader", {"SP Task": {"view": True, "assigned": True}})
		user = self.user_with("sp.pm.reader@example.com", "SP Task Reader")
		self.assertTrue(row_rules.restricted("SP Task", user))
		condition = row_rules.query_conditions(user, "SP Task")
		self.assertIn("assigned_to", condition)
		self.assertFalse(row_rules.restricted("SP Task", self.admin))
		frappe.get_doc("User", user).add_roles("SP Admin")
		self.assertFalse(row_rules.restricted("SP Task", user))  # the admin is never restricted
