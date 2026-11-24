"""dashboard.get (SP-148): the admin's command dashboard (AD1)."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe

ADMIN_ROLES = ("SP Admin", "System Manager")


def _admin() -> None:
	if not set(ADMIN_ROLES) & set(frappe.get_roles()):
		fail("NOT_PERMITTED", _("For the admin only."))


@endpoint(methods=("GET",))
def get(month: str | None = None) -> dict:
	_admin()
	from smart_power.dashboards.command import get as command

	return command(month)
