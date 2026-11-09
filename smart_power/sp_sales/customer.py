"""Customer master rules (SP-31): each customer is stored once, keyed by an Egyptian mobile."""

import re

import frappe
from frappe import _
from frappe.utils import get_link_to_form

# 11 digits: 010, 011, 012 or 015, then 8 digits (SP-31).
MOBILE_PATTERN = re.compile(r"^01[0125]\d{8}$")
COUNTRY_CODE = "20"
INTERNATIONAL_PREFIX = "00"


def normalize_mobile(value: str | None) -> str:
	"""Digits only, in the local form: "+20 100 123 4567" and "00201001234567" → "01001234567"."""
	digits = re.sub(r"\D", "", value or "")
	if digits.startswith(INTERNATIONAL_PREFIX + COUNTRY_CODE):
		digits = digits[len(INTERNATIONAL_PREFIX) :]
	if digits.startswith(COUNTRY_CODE):
		digits = "0" + digits[len(COUNTRY_CODE) :]
	return digits


def is_valid_mobile(value: str) -> bool:
	return bool(MOBILE_PATTERN.match(value or ""))


def find_by_mobile(mobile: str, exclude: str | None = None) -> str | None:
	"""The customer that already has this mobile, if any."""
	filters = {"sp_mobile": normalize_mobile(mobile)}
	if exclude:
		filters["name"] = ("!=", exclude)
	return frappe.db.get_value("Customer", filters)


def validate(doc, method=None):
	"""Customer validate hook: clean the mobiles, require one, and refuse a duplicate."""
	for fieldname in ("sp_mobile", "sp_mobile_2"):
		if doc.get(fieldname):
			doc.set(fieldname, normalize_mobile(doc.get(fieldname)))
			if not is_valid_mobile(doc.get(fieldname)):
				frappe.throw(
					_(
						"{0} is not a valid Egyptian mobile. Use 11 digits starting with 010, 011, 012 or 015."
					).format(frappe.bold(doc.get(fieldname))),
					title=_("Invalid mobile"),
				)

	if not doc.sp_mobile:
		if doc.get("is_internal_customer"):
			return
		frappe.throw(_("Mobile is required: it is how a returning customer is found."), frappe.MandatoryError)

	existing = find_by_mobile(doc.sp_mobile, exclude=doc.name)
	if existing:
		frappe.throw(
			_("Customer already exists: {0} has the mobile {1}.").format(
				get_link_to_form("Customer", existing), doc.sp_mobile
			),
			frappe.DuplicateEntryError,
			title=_("Customer already exists"),
		)
