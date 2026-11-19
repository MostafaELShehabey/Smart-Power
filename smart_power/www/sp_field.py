import frappe
from frappe import _

no_cache = 1


def _messages() -> dict:
	"""What the page's script says, in the user's language."""
	return {
		"saved": _("Saved"),
		"changed": _("Changed"),
		"failed": _("Not saved"),
		"uploading": _("Uploading…"),
		"uploaded": _("File ready"),
		"recording": _("Recording… tap to stop"),
		"record": _("Record a voice note"),
		"reason": _("Why should the day be reopened?"),
		"sent": _("Sent for a decision"),
		"waiting": _("Waiting for a decision"),
		"change": _("Edit"),
		"ask": _("Ask to Reopen"),
		"locked": _("Day locked"),
		"editing": _("Changing {0}"),
		"new_entry": _("New entry"),
		"choose": _("Choose…"),
		"none_open": _("No open jobs"),
	}


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/sp-field"
		raise frappe.Redirect
	context.no_header = False
	context.full_name = frappe.utils.get_fullname(frappe.session.user)
	context.title = _("Field entry")
	from smart_power.sp_winch.vehicles import driver_oil_note

	context.oil = driver_oil_note()  # the driver's vehicle (SP-106)
	from smart_power.sp_winch.bookings import todays_jobs

	context.jobs = todays_jobs()  # today's booked jobs (SP-107)
	from smart_power.sp_winch.field_lock import locking_soon, my_entries

	context.locking = len(locking_soon())  # entries locking in 24 hours (SP-109)
	context.entries = my_entries()
	# the Job, Expense and Money pages (SP-180) need the right to log an entry
	context.can_log = bool(frappe.has_permission("SP Field Entry", "create"))  # nosemgrep
	context.messages = _messages()
	return context
