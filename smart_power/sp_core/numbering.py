"""Document numbering (SP-134, X8): every numbered document, its format and its counter.

    get_numbering()                              the rows of the X8 numbering screen
    set_counter(doctype, series, value, reason)  move a counter (admin, with a reason, audited)

The counters are Frappe's own (the Series table, read and written through NamingSeries), so
this screen and the documents always agree. Formats with .YYYY. restart every year by
themselves. ERPNext documents change their format in Document Naming Settings; Smart Power's
own formats are part of the app.
"""

import re

import frappe
from frappe import _
from frappe.model.naming import NamingSeries
from frappe.utils import cint

from smart_power.constants import SP_MODULES
from smart_power.sp_core.services.audit import audit

ADMIN_ROLES = ("SP Admin", "System Manager")
# ERPNext documents Smart Power numbers (their formats come from their Naming Series options)
ERPNEXT_DOCTYPES = (
	"Quotation",
	"Customer",
	"Sales Order",
	"Sales Invoice",
	"Purchase Order",
	"Delivery Note",
	"Payment Entry",
)
FORMAT_PREFIX = "format:"
BRACES = re.compile(r"\{([^}]+)\}")


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin manages document numbering."), frappe.PermissionError)


def as_series(autoname: str | None) -> str | None:
	"""A DocType's autoname as a dot series (format:TASK-{YYYY}-{#####} -> TASK-.YYYY.-.#####),
	or None when it is not numbered."""
	autoname = (autoname or "").strip()
	if "#" not in autoname:
		return None
	if autoname.startswith(FORMAT_PREFIX):
		return BRACES.sub(lambda m: f".{m.group(1)}.", autoname.removeprefix(FORMAT_PREFIX)).strip(".")
	return autoname


def numbered() -> list[tuple[str, str, bool]]:
	"""(doctype, series, editable in Document Naming Settings) for every numbered document."""
	rows = []
	for doctype, autoname in frappe.get_all(
		"DocType",
		filters={"module": ("in", list(SP_MODULES)), "istable": 0},
		fields=["name", "autoname"],
		as_list=True,
	):
		series = as_series(autoname)
		if series:
			rows.append((doctype, series, False))
	for doctype in ERPNEXT_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		field = frappe.get_meta(doctype).get_field("naming_series")
		for option in (field.options or "").split("\n") if field else []:
			if option.strip():
				rows.append((doctype, option.strip(), True))
	return sorted(rows)


@frappe.whitelist()
def get_numbering() -> list[dict]:
	_check_admin()
	out = []
	for doctype, series, in_naming_settings in numbered():
		naming = NamingSeries(series)
		try:
			prefix = naming.get_prefix()
			current = naming.get_current_value()
		except frappe.ValidationError:
			continue  # a format that needs the document itself (e.g. a field), not shown
		digits = naming.series.count("#")  # Frappe adds .##### to a series without one
		out.append(
			{
				"doctype": doctype,
				"label": _(doctype),
				"series": series,
				"prefix": prefix,
				"current": current,
				"next": f"{prefix}{str(current + 1).zfill(digits)}",
				"yearly": ".YY" in series,
				"in_naming_settings": in_naming_settings,
			}
		)
	return out


# Smart Power records numbered by a dot series with its own yearly counter (SP-134). Their
# "format:" names used to share Frappe's one empty-prefix counter and never restarted.
YEARLY_DOCTYPES = ("SP Task", "SP Review Item", "SP Rule Override Log")


def start_counters_after_used(doctypes=YEARLY_DOCTYPES) -> None:
	"""Start each record's own counter after the highest number it already used, so a new name
	never clashes with an old one."""
	for doctype in doctypes:
		series = as_series(frappe.get_meta(doctype).autoname)
		if not series:
			continue
		naming = NamingSeries(series)
		used = highest_used(doctype, naming.get_prefix())
		if used > naming.get_current_value():
			naming.update_counter(used)


def highest_used(doctype: str, prefix: str) -> int:
	"""The highest number already used by a document with this prefix."""
	names = frappe.get_all(doctype, filters={"name": ("like", f"{prefix}%")}, pluck="name")
	numbers = [cint(name.removeprefix(prefix)) for name in names if name.removeprefix(prefix).isdigit()]
	return max(numbers, default=0)


@frappe.whitelist(methods=["POST"])
def set_counter(doctype: str, series: str, value: int, reason: str) -> int:
	"""Move a series counter (e.g. to start this year's stations after the paper ones). It can
	never go below a number already used: the next document would clash with an old one."""
	_check_admin()
	if (doctype, series) not in {(d, s) for d, s, _editable in numbered()}:
		frappe.throw(_("{0} is not a numbering series of {1}.").format(frappe.bold(series), _(doctype)))
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A reason is needed to change a counter."), frappe.MandatoryError)
	value = cint(value)
	naming = NamingSeries(series)
	prefix = naming.get_prefix()
	used = highest_used(doctype, prefix)
	if value < used:
		frappe.throw(
			_("{0} is already used up to {1}: the counter cannot go below {1}.").format(
				frappe.bold(prefix), frappe.bold(used)
			)
		)
	old = naming.get_current_value()
	naming.update_counter(value)
	audit(
		"Set naming counter", doctype, None, series=series, prefix=prefix, old=old, new=value, reason=reason
	)
	return value
