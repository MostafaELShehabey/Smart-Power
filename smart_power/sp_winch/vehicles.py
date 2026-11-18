"""Vehicles and equipment (SP-106, W4): the winch, the Jumbo car and any new vehicle.

Each vehicle is an ERPNext Vehicle with its financial center, driver and oil-change record. The
winch and the Jumbo car post to their own centers. For another vehicle the admin adds a cost center
and chooses it here; it then joins the center picker.

    next oil = last oil + interval     the interval defaults from Smart Power Settings
    record_odometer(...)               a reading from the field; an oil change resets the reminder
    check_oil_due()                    daily: the driver and the winch manager are told once
"""

import frappe
from frappe import _
from frappe.utils import cint

from smart_power.notify import send
from smart_power.sp_core.services.settings import get_value
from smart_power.sp_finance.centers import JUMBO, WINCH, center

VEHICLE = "Vehicle"
WINCH_TYPE, JUMBO_TYPE, OTHER_TYPE = "Winch", "Jumbo", "Other"
CENTER_OF = {WINCH_TYPE: WINCH, JUMBO_TYPE: JUMBO}
KILOMETER, DIESEL = "Kilometer", "Diesel"
EVENT_OIL = "oil_change_due"
MANAGER = "SP Winch Manager"


def _company() -> str | None:
	from smart_power.sp_stock.consignment import _default_company

	return _default_company()


def before_validate(doc, method=None) -> None:
	"""Vehicle before_validate: what ERPNext requires and Smart Power does not track, then the oil."""
	label = doc.get("sp_vehicle_type") or OTHER_TYPE
	doc.make = doc.make or label
	doc.model = doc.model or label
	doc.uom = doc.uom or KILOMETER
	doc.fuel_type = doc.fuel_type or DIESEL
	doc.company = doc.get("company") or _company()
	doc.sp_odometer_km = cint(doc.get("sp_odometer_km"))
	if doc.is_new():  # ERPNext fixes this field once saved, so the reading lives on sp_odometer_km
		doc.last_odometer = doc.sp_odometer_km
	doc.sp_oil_interval_km = cint(doc.get("sp_oil_interval_km")) or cint(get_value("oil_interval_km"))
	doc.sp_next_oil_km = cint(doc.get("sp_last_oil_km")) + cint(doc.sp_oil_interval_km)
	key = CENTER_OF.get(doc.get("sp_vehicle_type"))
	if key and not doc.get("sp_cost_center"):
		doc.sp_cost_center = center(key, doc.company)


def validate(doc, method=None) -> None:
	if not doc.get("sp_cost_center"):
		frappe.throw(_("Choose the vehicle's financial center."), frappe.MandatoryError)
	if cint(doc.sp_oil_interval_km) <= 0:
		frappe.throw(_("Set the oil change interval."), frappe.MandatoryError)
	if cint(doc.get("sp_last_oil_km")) > cint(doc.sp_odometer_km):
		frappe.throw(_("The last oil change cannot be after the current odometer."))


def km_to_oil(doc) -> int:
	return cint(doc.get("sp_next_oil_km")) - cint(doc.get("sp_odometer_km"))


def record_odometer(vehicle: str, km: int, oil_changed: bool = False) -> None:
	"""A reading from the field. An oil change starts the next interval from this reading."""
	doc = frappe.get_doc(VEHICLE, vehicle)
	if cint(km) < cint(doc.sp_odometer_km):
		frappe.throw(_("The odometer cannot go back from {0} km.").format(doc.sp_odometer_km))
	doc.sp_odometer_km = cint(km)
	if oil_changed:
		doc.sp_last_oil_km = cint(km)
		doc.sp_oil_alerted_at = 0
	doc.flags.ignore_permissions = True
	doc.save()


def driver_oil_note(user: str | None = None) -> dict | None:
	"""What the driver's home shows about their vehicle."""
	user = user or frappe.session.user
	row = frappe.db.get_value(
		VEHICLE,
		{"sp_driver_user": user},
		["name", "sp_odometer_km", "sp_next_oil_km"],
		as_dict=True,
	)
	if not row:
		return None
	left = km_to_oil(row)
	return {
		"vehicle": row.name,
		"km_left": left,
		"overdue": left < 0,
		"label": _("{0} km to oil").format(left)
		if left >= 0
		else _("Oil change is {0} km late").format(-left),
	}


def _managers() -> list[str]:
	users = frappe.get_all("Has Role", {"role": MANAGER, "parenttype": "User"}, pluck="parent")
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


def check_oil_due() -> None:
	"""Daily: a vehicle close to its oil change alerts its driver and the winch manager, once."""
	margin = cint(get_value("oil_alert_km"))
	rows = frappe.get_all(
		VEHICLE,
		fields=["name", "sp_odometer_km", "sp_next_oil_km", "sp_driver_user", "sp_oil_alerted_at"],
	)
	managers = _managers()
	for row in rows:
		if km_to_oil(row) > margin or cint(row.sp_oil_alerted_at) == cint(row.sp_next_oil_km):
			continue
		users = sorted({*managers, row.sp_driver_user} - {None, ""})
		subject = _("{0}: {1} km to the oil change").format(row.name, km_to_oil(row))
		send(EVENT_OIL, users, VEHICLE, row.name, subject)
		frappe.db.set_value(VEHICLE, row.name, "sp_oil_alerted_at", row.sp_next_oil_km, update_modified=False)
