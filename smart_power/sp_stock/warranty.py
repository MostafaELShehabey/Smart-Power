"""The warranty register per serial (SP-179): customer, station or showroom sale, start basis,
months and end date.

- A station's components: from the commissioning's operation date. Written when the
  commissioning is submitted and again at the technical close, which settles the months from the
  approved quote (SP-80). Cancelling the commissioning voids its rows.
- A showroom sale: from the sale date, the item's warranty years, else its brand's (SP-179's
  showroom branch).
- The cover ends on the same date that many months later (owner, 2026-11-22): 10-1-2027 + 12
  months -> 10-1-2028.
"""

import frappe
from frappe.utils import add_months, cint, getdate

WARRANTY, COMMISSIONING, COMPONENT = "SP Warranty", "SP Commissioning", "SP Station Component"
ACTIVE, VOID = "Active", "Void"
STATION, SHOWROOM = "Station", "Showroom sale"
OPERATION_DATE, SALE_DATE = "Operation date", "Sale date"


def end_date(start, months) -> str | None:
	"""10-1-2027 + 12 months -> 10-1-2028 (owner, 2026-11-22)."""
	if not start or not cint(months):
		return None
	return str(add_months(getdate(start), cint(months)))


def upsert(serial: str, item: str | None, values: dict) -> str:
	"""The serial's active row for this source, created or brought up to date."""
	key = {"serial_no": serial, "status": ACTIVE}
	for field in ("commissioning", "sales_invoice"):
		if values.get(field):
			key[field] = values[field]
	name = frappe.db.get_value(WARRANTY, key)
	months = cint(values.get("months"))
	row = {
		**values,
		"serial_no": serial,
		"item": item,
		"months": months,
		"end_date": end_date(values.get("start_date"), months),
		"status": ACTIVE,
	}
	doc = frappe.get_doc(WARRANTY, name) if name else frappe.new_doc(WARRANTY)
	doc.update(row)
	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def void(filters: dict, reason: str) -> None:
	for name in frappe.get_all(WARRANTY, {**filters, "status": ACTIVE}, pluck="name"):
		frappe.db.set_value(WARRANTY, name, {"status": VOID, "void_reason": reason})


# --- stations -----------------------------------------------------------------------------------


def register_commissioning(doc, start=None) -> None:
	"""One row per component with a serial, from the operation date (the station's, at the close)."""
	customer = frappe.db.get_value("SP Station", doc.station, "customer")
	for row in doc.components:
		if not (row.serial or "").strip():
			continue
		upsert(
			row.serial.strip(),
			row.item,
			{
				"source": STATION,
				"station": doc.station,
				"commissioning": doc.name,
				"customer": customer,
				"start_basis": OPERATION_DATE,
				"start_date": start or doc.operation_date,
				"months": row.warranty_months,
				"nameplate_photo": row.nameplate_photo,
			},
		)


def register_station(station: str) -> None:
	"""At the technical close, the components' settled months (SP-80) and the station's date."""
	start = frappe.db.get_value("SP Station", station, "operation_date")
	for name in frappe.get_all(COMMISSIONING, {"station": station, "docstatus": 1}, pluck="name"):
		register_commissioning(frappe.get_doc(COMMISSIONING, name), start)


def on_commissioning_cancel(doc) -> None:
	from frappe import _

	void({"commissioning": doc.name}, _("Commissioning {0} was cancelled.").format(doc.name))
