"""Request hooks for the desk."""

import frappe
from werkzeug.routing import RequestRedirect

from smart_power.sp_core.setup.role_catalogue import LIGHT_ENTRY_ROLES

FIELD_PAGE = "/sp-field"
DESK_PATHS = ("/desk", "/app")
DESK_HOMES = {*DESK_PATHS, *(f"{path}/home" for path in DESK_PATHS)}
LIGHT_ENTRY = "Light"


def redirect_light_users() -> None:
	"""Light users land on the field page instead of the desk.

	Drivers and the winch operator have no desk at all: any desk page sends them there (SP-34).
	An office user the admin set to the light entry (SP-130) lands there when opening the desk
	home, and can still open a desk link they were sent.
	"""
	request = getattr(frappe.local, "request", None)
	if not request or request.method != "GET" or not request.path.startswith(DESK_PATHS):
		return
	user = frappe.session.user
	if user == "Guest":
		return
	if frappe.session.data.get("user_type") == "Website User":
		if set(LIGHT_ENTRY_ROLES) & set(frappe.get_roles(user)):
			raise RequestRedirect(FIELD_PAGE)
		return
	if (
		request.path.rstrip("/") in DESK_HOMES
		and frappe.db.get_value("User", user, "sp_entry_mode") == LIGHT_ENTRY
	):
		raise RequestRedirect(FIELD_PAGE)
