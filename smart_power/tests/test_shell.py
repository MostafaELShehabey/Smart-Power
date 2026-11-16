"""The app shell (SP-37): Smart Power's dock of module-group sidebars, filtered by role."""

import frappe
from frappe.boot import get_module_sidebars
from frappe.desk.doctype.dock.dock import resolve_dock
from frappe.tests import IntegrationTestCase

from smart_power.shell import apply_to_boot
from smart_power.sp_core.setup.role_catalogue import PROFILES
from smart_power.tests.utils import make_user

GROUPS = (
	"Smart Power",
	"Requests & Customers",
	"Follow-up",
	"Quotes",
	"Stations",
	"Purchasing",
	"Inventory",
	"Finance",
	"Reports",
	"Admin Studio",
)


def profile_keys(name: str) -> tuple:
	return next(p.keys for p in PROFILES if p.name == name)


def rail(user: str) -> dict:
	"""The Smart Power rail the user sees: each group they can open, with its items."""
	frappe.set_user(user)
	try:
		frappe.clear_cache(user=user)
		boot = frappe._dict(module_sidebars=get_module_sidebars(), dock=resolve_dock())
		apply_to_boot(boot)  # as the desk's boot does (boot_session)
		sidebars, dock = boot.module_sidebars, boot.dock.get("smart_power") or []
		return {
			row["link_to"]: [i["label"] for i in sidebars[row["link_to"]]["items"] if i.get("type") == "Link"]
			for row in dock
			if not row.get("hidden") and row.get("link_to") in sidebars
		}
	finally:
		frappe.set_user("Administrator")


class TestShell(IntegrationTestCase):
	def test_the_admin_sees_every_group(self):
		admin = make_user("sp.shell.admin@example.com", ("admin",))
		self.assertEqual(list(rail(admin)), list(GROUPS))

	def test_the_store_keeper_sees_only_home_inventory_purchasing_and_his_tasks(self):
		# محمد جابر: main store keeper and installation technician
		jaber = make_user("sp.shell.jaber@example.com", profile_keys("SP Store and Installations"))
		groups = rail(jaber)
		self.assertEqual(set(groups), {"Smart Power", "Purchasing", "Inventory"})
		self.assertIn("My Tasks", groups["Smart Power"])
		self.assertIn("Receive Goods", groups["Purchasing"])

	def test_the_call_centre_has_no_admin_or_stock_groups(self):
		camelia = make_user("sp.shell.camelia@example.com", profile_keys("SP Call Center"))
		groups = rail(camelia)
		self.assertIn("Requests & Customers", groups)
		self.assertIn("Follow-up", groups)
		self.assertFalse({"Admin Studio", "Inventory", "Purchasing", "Finance"} & set(groups))
