import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/sp-field"
		raise frappe.Redirect
	context.no_header = False
	context.full_name = frappe.utils.get_fullname(frappe.session.user)
	context.title = _("Field entry")
	return context
