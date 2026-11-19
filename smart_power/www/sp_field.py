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
	from smart_power.sp_winch.vehicles import driver_oil_note

	context.oil = driver_oil_note()  # the driver's vehicle (SP-106)
	from smart_power.sp_winch.bookings import todays_jobs

	context.jobs = todays_jobs()  # today's booked jobs (SP-107)
	from smart_power.sp_winch.field_lock import locking_soon, my_entries

	context.locking = len(locking_soon())  # entries locking in 24 hours (SP-109)
	context.entries = my_entries()
	return context
