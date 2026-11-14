# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

"""A calculation template (SP-55, X7): the inputs and lines one offer type is priced from.

Templates are versioned: every version is its own document, named <code>-v<version>. A
published version cannot change (a quote stores the version it used); "New Version" copies it
into an editable draft. One version is published per offer type (and per factory for chassis
templates). Every number is template data, never code.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Max
from frappe.utils import cint, now_datetime

from smart_power.sp_quotes import formulas

BRAND_PRIORITY, FIRST_IN_STOCK = "Brand priority", "First in stock"
LOCKED_BTC = "Locked BTC price"
NUMBER_INPUTS = ("Float", "Int")
# Edits allowed on a published version
STATUS_FIELDS = ("is_published", "published_on", "description")


class SPCalcTemplate(Document):
	def autoname(self):
		self.template_key = (self.template_key or "").strip().upper()
		self.version = next_version(self.template_key)
		self.name = f"{self.template_key}-v{self.version}"

	def validate(self):
		self.check_published_is_frozen()
		input_keys = self.check_inputs()
		self.check_lines(input_keys)

	def check_published_is_frozen(self):
		before = None if self.is_new() else self.get_doc_before_save()
		# a published version, or one a quote was calculated from, never changes
		frozen = before and (
			before.is_published or frappe.db.exists("Quotation", {"sp_calc_template": self.name})
		)
		if frozen and content(before) != content(self):
			frappe.throw(
				_(
					"Version {0} is published or used by a quote and cannot change. Make a new version."
				).format(frappe.bold(self.name)),
				title=_("Published template"),
			)

	def check_inputs(self) -> set[str]:
		keys = set()
		for row in self.inputs:
			where = _("Input {0}").format(row.idx)
			row.input_key = formulas.check_key(row.input_key, where)
			if row.input_key in keys:
				frappe.throw(_("{0}: the key {1} is used twice.").format(where, frappe.bold(row.input_key)))
			keys.add(row.input_key)
			check_default(row, where)
		return keys

	def check_lines(self, input_keys: set[str]) -> None:
		known = set(input_keys) | {formulas.SETTINGS}
		for row in self.lines:
			where = _("Line {0}").format(frappe.bold(row.line_key or row.idx))
			row.line_key = formulas.check_key(row.line_key, where)
			if row.line_key in known:
				frappe.throw(
					_("{0}: the key {1} is already an input or a line.").format(
						where, frappe.bold(row.line_key)
					)
				)
			# a line's formulas see the inputs, the lines above it and its own picked item
			formulas.check(row.qty_formula or "1", known | {formulas.ITEM}, where)
			if row.selection_rule == BRAND_PRIORITY:
				if not (row.item_group and row.capacity_field and row.need_formula):
					frappe.throw(
						_(
							"{0}: brand priority needs an item group, a capacity spec and a need formula."
						).format(where)
					)
				formulas.check(row.need_formula, known, where)
			elif row.selection_rule == FIRST_IN_STOCK and not row.item_group:
				frappe.throw(_("{0}: first in stock needs an item group.").format(where))
			if row.pricing_method == LOCKED_BTC:
				row.lock_markup = 1
			known.add(row.line_key)

	@frappe.whitelist()
	def publish(self):
		"""Publish this version; the other published version of the same offer type stops."""
		self.check_permission("write")
		if not self.lines:
			frappe.throw(_("A template needs at least one line before it is published."))
		template = frappe.qb.DocType("SP Calc Template")
		others = (
			frappe.qb.from_(template)
			.select(template.name)
			.where(template.is_published == 1)
			.where(template.offer_type == self.offer_type)
			.where(template.name != self.name)
		)
		if self.factory:
			others = others.where(template.factory == self.factory)
		else:
			others = others.where(template.factory.isnull() | (template.factory == ""))
		for (name,) in others.run():
			frappe.db.set_value("SP Calc Template", name, "is_published", 0)
		self.db_set({"is_published": 1, "published_on": now_datetime()})
		self.add_comment("Info", _("Published"))

	@frappe.whitelist()
	def unpublish(self):
		self.check_permission("write")
		self.db_set("is_published", 0)
		self.add_comment("Info", _("Unpublished"))

	@frappe.whitelist()
	def run_sample(self, inputs: dict | str | None = None) -> dict:
		"""Price this template (as it is on the form) with sample inputs; nothing is saved."""
		from smart_power.sp_quotes.engine import calculate

		self.check_permission("read")
		return calculate(self, frappe.parse_json(inputs) or {})

	@frappe.whitelist()
	def new_version(self) -> str:
		"""An editable copy as the next version."""
		frappe.has_permission("SP Calc Template", "create", throw=True)
		copy = frappe.copy_doc(self)
		copy.previous_version = self.name
		copy.insert()
		return copy.name


def next_version(template_key: str) -> int:
	template = frappe.qb.DocType("SP Calc Template")
	(last,) = (
		frappe.qb.from_(template).select(Max(template.version)).where(template.template_key == template_key)
	).run()[0]
	return cint(last) + 1


def published_template(offer_type: str, factory: str | None = None) -> str | None:
	"""The published version for an offer type (and factory, for chassis)."""
	filters = {"offer_type": offer_type, "is_published": 1}
	if factory:
		filters["factory"] = factory
	return frappe.db.get_value("SP Calc Template", filters, "name")


def content(doc) -> str:
	"""What a published version freezes: everything but its publish status and notes."""
	data = doc.as_dict(no_default_fields=True)
	for field in (*STATUS_FIELDS, "version", "previous_version", "template_key"):
		data.pop(field, None)
	for table in ("inputs", "lines"):
		data[table] = [
			{k: v for k, v in row.items() if k not in ("name", "idx", "parent", "parentfield", "parenttype")}
			for row in data.get(table) or []
		]
	return json.dumps(data, sort_keys=True, default=str)


def check_default(row, where: str) -> None:
	value = row.default_value
	if row.input_type == "Select":
		options = [o.strip() for o in (row.options or "").split("\n") if o.strip()]
		if not options:
			frappe.throw(_("{0}: a Select input needs its options.").format(where))
		if value not in (None, "") and value not in options:
			frappe.throw(
				_("{0}: the default {1} is not one of the options.").format(where, frappe.bold(value))
			)
	elif row.input_type in NUMBER_INPUTS and value not in (None, ""):
		try:
			float(value)
		except ValueError:
			frappe.throw(_("{0}: the default {1} is not a number.").format(where, frappe.bold(value)))
