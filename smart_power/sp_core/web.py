"""Request hooks for the desk."""

import frappe
from frappe.apps import get_default_path
from werkzeug.routing import RequestRedirect

from smart_power.hooks import app_home as APP_HOME
from smart_power.sp_core.setup.role_catalogue import LIGHT_ENTRY_ROLES

FIELD_PAGE = "/sp-field"
DESK_PATHS = ("/desk", "/app")
DESK_HOMES = {*DESK_PATHS, *(f"{path}/home" for path in DESK_PATHS)}
LIGHT_ENTRY = "Light"
# the app's own address with no page after it: the desk has nothing to show there (BUG-3)
APP_ROOTS = {f"{path}/{APP_HOME.split('/')[2]}" for path in DESK_PATHS}


def redirect_light_users() -> None:
	"""Light users land on the field page instead of the desk; full users on their app's home.

	Drivers and the winch operator have no desk at all: any desk page sends them there (SP-34).
	An office user the admin set to the light entry (SP-130) lands there when opening the desk
	home, and can still open a desk link they were sent. Everyone else opening the bare desk goes
	to their default app's home, the Smart Power home unless they picked another (BUG-2): Frappe
	would show its app chooser there, the desk home being the setup wizard only the admin may open.
	The app's bare address, a refresh or a shared link of the app root, opens the app's home.
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
	path = request.path.rstrip("/")
	if path in DESK_HOMES and frappe.db.get_value("User", user, "sp_entry_mode") == LIGHT_ENTRY:
		raise RequestRedirect(FIELD_PAGE)
	if path in DESK_PATHS and (home := app_home()):
		raise RequestRedirect(home)
	if path in APP_ROOTS:
		raise RequestRedirect(APP_HOME)


def app_home() -> str | None:
	"""The user's default app's home, or None while the setup wizard is still to run."""
	if not frappe.is_setup_complete():
		return None
	home = get_default_path()
	return home if home and home.rstrip("/") not in DESK_HOMES else None
