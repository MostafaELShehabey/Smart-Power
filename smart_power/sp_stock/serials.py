"""Serial numbers, phase 1 (SP-179; decisions 62 and 73): motors and pumps, one item group at a time.

- An Item Group's "Serial Numbers" flag (sp_serial_tracked) makes the items of that group and of
  its sub-groups serial-tracked (ERPNext has_serial_no; v16 keeps the serials in a Serial and Batch
  Bundle). Seeded on the motor and pump groups; the admin turns it on for inverters or batteries
  later. An item that already moved stock without serials keeps has_serial_no off: ERPNext cannot
  switch it, and the flag says which were skipped.
- A serial-tracked unit needs its serial and a new nameplate photo at every point (owner,
  2026-11-22): the receipt (SP-84, on the receipt line), the issue or transfer to a site and the
  showroom sale (an SP Serial Photo each), and commissioning (on the component).
- history(serial) is the lookup for service: every movement, photo, commissioning and warranty.
"""

import frappe
from frappe import _
from frappe.utils import cstr

from smart_power.sp_core.setup.seed import defaults

GROUP, FLAG, PHOTO = "Item Group", "sp_serial_tracked", "SP Serial Photo"
ISSUE, SHOWROOM_SALE = "Issue", "Showroom sale"


# --- which items --------------------------------------------------------------------------------


def tracked_group(group: str | None) -> bool:
	"""The group, or one of the groups above it, has the Serial Numbers flag."""
	if not group or not frappe.get_meta(GROUP).has_field(FLAG):
		return False
	lft, rgt = frappe.get_cached_value(GROUP, group, ["lft", "rgt"]) or (None, None)
	if lft is None:
		return False
	return bool(frappe.db.exists(GROUP, {"lft": ("<=", lft), "rgt": (">=", rgt), FLAG: 1}))


def is_serial(item_code: str | None) -> bool:
	return bool(item_code and frappe.get_cached_value("Item", item_code, "has_serial_no"))


def _moved(item_code: str) -> bool:
	return bool(frappe.db.exists("Stock Ledger Entry", {"item_code": item_code, "is_cancelled": 0}))


def item_validate(doc) -> None:
	"""Item validate: an item of a serial-tracked group is serial-tracked, unless it already moved
	stock without serials (ERPNext refuses that change)."""
	if doc.has_serial_no or doc.is_stock_item == 0 or not tracked_group(doc.item_group):
		return
	if doc.is_new() or not _moved(doc.name):
		doc.has_serial_no = 1


def _groups_under(group: str) -> list[str]:
	lft, rgt = frappe.db.get_value(GROUP, group, ["lft", "rgt"])
	return frappe.get_all(GROUP, {"lft": (">=", lft), "rgt": ("<=", rgt)}, pluck="name")


def apply_group(group: str) -> dict:
	"""Make the group's items serial-tracked; those that already moved stock are skipped."""
	items = frappe.get_all(
		"Item",
		{"item_group": ("in", _groups_under(group)), "has_serial_no": 0, "is_stock_item": 1},
		pluck="name",
	)
	skipped = [i for i in items if _moved(i)]
	switched = [i for i in items if i not in skipped]
	for name in switched:
		frappe.db.set_value("Item", name, "has_serial_no", 1)
	return {"switched": switched, "skipped": skipped}


def item_group_on_update(doc, method=None) -> None:
	"""Item Group on_update: turning the flag on switches its items."""
	before = doc.get_doc_before_save()
	if not doc.get(FLAG) or (before and before.get(FLAG)):
		return
	result = apply_group(doc.name)
	message = _("{0} items are now tracked by serial number.").format(len(result["switched"]))
	if result["skipped"]:
		message += " " + _("Not switched, because they already have stock movements: {0}").format(
			", ".join(result["skipped"])
		)
	frappe.msgprint(message, alert=not result["skipped"])


def seed_serial_groups() -> None:
	"""Phase 1: the motor and pump groups (defaults item_groups.serials), once."""
	if not frappe.get_meta(GROUP).has_field(FLAG):
		return
	for name in defaults()["item_groups"].get("serials") or []:
		if frappe.db.exists(GROUP, name) and not frappe.db.get_value(GROUP, name, FLAG):
			frappe.db.set_value(GROUP, name, FLAG, 1)
			apply_group(name)


# --- the nameplate photo ------------------------------------------------------------------------


def unit_serials(item_code: str, qty: float, text: str | list | None) -> list[str]:
	"""One different serial for each unit of a serial-tracked item."""
	if isinstance(text, list):
		serials = [cstr(s).strip() for s in text if cstr(s).strip()]
	else:
		serials = [s.strip() for s in cstr(text).replace(",", "\n").split("\n") if s.strip()]
	if len(set(serials)) != len(serials) or len(serials) != qty:
		if qty == 1:
			frappe.throw(_("{0}: enter its serial number.").format(item_code))
		frappe.throw(_("{0}: enter {1} different serial numbers.").format(item_code, frappe.format(qty)))
	return serials


def check_photos(item_code: str, serials: list[str], photos: dict) -> None:
	"""Every unit needs its nameplate photo, one the user uploaded."""
	missing = [s for s in serials if not (photos or {}).get(s)]
	if missing:
		frappe.throw(
			_("{0}: attach the nameplate photo of {1}.").format(item_code, ", ".join(missing)),
			frappe.MandatoryError,
		)
	for s in serials:
		url = photos[s]
		if not frappe.db.exists("File", {"file_url": url, "owner": frappe.session.user}):
			frappe.throw(_("Attach a photo you uploaded yourself."), frappe.PermissionError)


def record_photos(
	point: str, item_code: str, serials: list[str], photos: dict, doctype: str, name: str, posting_date
) -> list[str]:
	"""One SP Serial Photo per unit; the uploaded file joins it, so whoever may read it can open it."""
	made = []
	for s in serials:
		row = frappe.get_doc(
			{
				"doctype": PHOTO,
				"serial_no": s,
				"item_code": item_code,
				"point": point,
				"reference_doctype": doctype,
				"reference_name": name,
				"posting_date": posting_date,
				"taken_by": frappe.session.user,
				"photo": photos[s],
			}
		)
		row.insert(ignore_permissions=True)
		_attach(photos[s], row.name)
		made.append(row.name)
	return made


def _attach(file_url: str, name: str) -> None:
	file = frappe.db.get_value(
		"File", {"file_url": file_url, "owner": frappe.session.user, "attached_to_name": ("is", "not set")}
	)
	if file:
		frappe.db.set_value(
			"File",
			file,
			{"attached_to_doctype": PHOTO, "attached_to_name": name, "attached_to_field": "photo"},
		)


# --- the lookup by serial -------------------------------------------------------------------------


def history(serial: str) -> list[dict]:
	"""Everything known of one serial, oldest first: stock movements, photos, commissioning and the
	warranty."""
	serial = cstr(serial).strip()
	if not serial:
		return []
	rows = []
	moves = frappe.db.sql(
		"""select date(b.posting_datetime) as posting_date, b.posting_datetime as at, b.voucher_type,
			b.voucher_no, b.warehouse, b.type_of_transaction, b.item_code
		from `tabSerial and Batch Entry` e join `tabSerial and Batch Bundle` b on b.name = e.parent
		where e.serial_no = %s and b.docstatus = 1 and b.is_cancelled = 0
		order by b.posting_datetime, b.creation""",
		serial,
		as_dict=True,
	)
	for m in moves:
		rows.append(
			{
				"date": m.posting_date,
				"event": _("Into {0}").format(m.warehouse)
				if m.type_of_transaction == "Inward"
				else _("Out of {0}").format(m.warehouse),
				"item": m.item_code,
				"reference_doctype": m.voucher_type,
				"reference_name": m.voucher_no,
				"photo": _receipt_photo(m.voucher_type, m.voucher_no, serial),
				"at": m.at,
			}
		)
	for p in frappe.get_all(
		PHOTO,
		{"serial_no": serial},
		["posting_date", "point", "item_code", "reference_doctype", "reference_name", "photo", "creation"],
	):
		rows.append(
			{
				"date": p.posting_date,
				"event": _("Nameplate photo: {0}").format(_(p.point)),
				"item": p.item_code,
				"reference_doctype": p.reference_doctype,
				"reference_name": p.reference_name,
				"photo": p.photo,
				"at": p.creation,
			}
		)
	for c in frappe.db.sql(
		"""select m.operation_date, m.name, m.station, c.item, c.nameplate_photo, m.modified as at
		from `tabSP Station Component` c join `tabSP Commissioning` m on m.name = c.parent
		where c.parenttype = 'SP Commissioning' and c.serial = %s and m.docstatus = 1""",
		serial,
		as_dict=True,
	):
		rows.append(
			{
				"date": c.operation_date,
				"event": _("Commissioned at station {0}").format(c.station),
				"item": c.item,
				"reference_doctype": "SP Commissioning",
				"reference_name": c.name,
				"photo": c.nameplate_photo,
				"at": c.at,
			}
		)
	for w in frappe.get_all(
		"SP Warranty",
		{"serial_no": serial},
		["name", "start_date", "end_date", "item", "customer_name", "status", "creation"],
	):
		rows.append(
			{
				"date": w.start_date,
				"event": _("Warranty to {0} ({1})").format(
					frappe.format(w.end_date, "Date") if w.end_date else _("no cover set"), _(w.status)
				),
				"item": w.item,
				"customer": w.customer_name,
				"reference_doctype": "SP Warranty",
				"reference_name": w.name,
				"at": w.creation,
			}
		)
	rows.sort(key=lambda r: (str(r.get("date") or ""), str(r.get("at") or "")))  # same day: by time
	for r in rows:
		r.pop("at", None)
	return rows


def _receipt_photo(voucher_type: str, voucher_no: str, serial: str) -> str | None:
	if voucher_type != "Purchase Receipt":
		return None
	return frappe.db.get_value(
		"Purchase Receipt Item", {"parent": voucher_no, "serial_no": serial}, "sp_serial_photo"
	)
