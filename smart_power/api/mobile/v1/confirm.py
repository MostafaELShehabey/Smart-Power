"""confirm.list / confirm.action (SP-148, M14): the admin's confirmations centre."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe

ADMIN_ROLES = ("SP Admin", "System Manager")


def _admin() -> None:
	if not set(ADMIN_ROLES) & set(frappe.get_roles()):
		fail("NOT_PERMITTED", _("For the admin only."))


@endpoint(methods=("GET",))
def list() -> dict:
	_admin()
	from smart_power.sp_finance.confirmations import pending

	return pending()


@endpoint(methods=("POST",))
def action(doctype: str, name: str, action: str, reason: str | None = None) -> dict:
	_admin()
	from smart_power.sp_finance import confirmations

	if action == "confirm":
		return {"ok": True, "result": confirmations.confirm(doctype, name)}
	if action == "reject":
		return {"ok": True, "result": confirmations.reject(doctype, name, reason)}
	fail("VALIDATION", _("Unknown action {0}.").format(action))
