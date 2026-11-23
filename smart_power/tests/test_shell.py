"""The app shell (SP-37): Smart Power's dock of module-group sidebars by role, "+ New", the counts."""

import frappe
from frappe.boot import get_module_sidebars
from frappe.desk.doctype.dock.dock import resolve_dock
from frappe.tests import IntegrationTestCase

from smart_power.shell import apply_to_boot, get_counts, get_new_menu
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
	"Winch",
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

	def test_the_compliance_officer_reaches_her_screens_and_not_the_contracts(self):
		# آية: technical office with regulatory compliance (RG1, SP-101)
		aya = make_user("sp.shell.aya@example.com", profile_keys("SP Technical Office"))
		stations = rail(aya)["Stations"]
		self.assertLessEqual(
			{"Installed Capacity", "Compliance Documents", "Compliance Reports"}, set(stations)
		)
		self.assertNotIn("Contracts", stations)
		# the items a role does not use stay hidden in Arabic too: the boot's labels are translated
		frappe.local.lang = "ar"
		try:
			arabic = rail(aya)["Stations"]
		finally:
			frappe.local.lang = "en"
		self.assertIn("مستندات التأهيل", arabic)
		self.assertNotIn("العقود", arabic)
		# and a projects manager does not get the compliance screens
		amira = make_user("sp.shell.amira@example.com", profile_keys("SP Projects Manager"))
		self.assertFalse({"Compliance Documents", "Compliance Reports"} & set(rail(amira)["Stations"]))

	def test_the_design_tools_show_to_the_quote_creator_only(self):
		# T1 design tools (SP-65): the follow-up lead sees the quotes, not the tools
		creator = make_user("sp.shell.creator@example.com", ("quote_creator",))
		self.assertIn("Design Tools", rail(creator)["Quotes"])
		lead = make_user("sp.shell.lead@example.com", ("followup_all",))
		self.assertNotIn("Design Tools", rail(lead)["Quotes"])


class TestNewMenuAndCounts(IntegrationTestCase):
	def menu(self, user):
		frappe.set_user(user)
		try:
			return [a["key"] for a in get_new_menu()]
		finally:
			frappe.set_user("Administrator")

	def test_new_offers_only_what_the_user_may_start(self):
		# محمد حسين: showroom and winch (showroom sale and winch booking join when built)
		hussein = make_user("sp.shell.hussein@example.com", profile_keys("SP Showroom and Winch"))
		keys = self.menu(hussein)
		self.assertIn("quote_request", keys)
		self.assertIn("payment", keys)
		self.assertNotIn("purchase_order", keys)
		jaber = make_user("sp.shell.jaber@example.com", profile_keys("SP Store and Installations"))
		self.assertFalse({"quote_request", "payment", "purchase_order"} & set(self.menu(jaber)))
		amira = make_user("sp.shell.amira@example.com", profile_keys("SP Projects Manager"))
		self.assertIn("purchase_order", self.menu(amira))

	def test_the_counts_follow_the_inbox(self):
		from smart_power.sp_core.inbox import create_task

		aya = make_user("sp.shell.aya@example.com", ("quote_creator",))
		frappe.set_user(aya)
		before = get_counts()["tasks"]
		frappe.set_user("Administrator")
		create_task("Other", "User", aya, aya, "مهمة للعدّاد")
		frappe.set_user(aya)
		self.assertEqual(get_counts()["tasks"], before + 1)
		frappe.set_user("Administrator")

	def test_a_new_task_is_pushed_to_its_assignee_at_once(self):
		# the dock's count and the open inbox listen to this (realtime needs socket.io, not up in tests)
		from unittest.mock import patch

		from smart_power.sp_core.inbox import REALTIME_EVENT, create_task

		aya = make_user("sp.shell.aya@example.com", ("quote_creator",))
		with patch("frappe.publish_realtime") as push:
			create_task("Other", "User", "Guest", aya, "مهمة تُدفع فورًا")
		self.assertTrue(
			any(c.args[0] == REALTIME_EVENT and c.kwargs.get("user") == aya for c in push.call_args_list)
		)
