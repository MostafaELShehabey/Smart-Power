"""Request hooks for the desk."""

import frappe
from werkzeug.routing import RequestRedirect

from smart_power.sp_core.setup.role_catalogue import LIGHT_ENTRY_ROLES

FIELD_PAGE = "/sp-field"
DESK_PATHS = ("/desk", "/app")


def redirect_light_users() -> None:
	"""Drivers and the winch operator have no desk access: /desk sends them to the field page (SP-34)."""
	request = getattr(frappe.local, "request", None)
	if not request or request.method != "GET" or not request.path.startswith(DESK_PATHS):
		return
	user = frappe.session.user
	if user == "Guest" or frappe.session.data.get("user_type") != "Website User":
		return
	if set(LIGHT_ENTRY_ROLES) & set(frappe.get_roles(user)):
		raise RequestRedirect(FIELD_PAGE)
