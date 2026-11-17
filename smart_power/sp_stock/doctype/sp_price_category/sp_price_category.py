# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from smart_power.sp_stock.prices import RULE_BASE, RULE_TARGET


class SPPriceCategory(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from smart_power.sp_stock.doctype.sp_price_rule.sp_price_rule import SPPriceRule

		amber_after_days: DF.Int
		category_name: DF.Data
		description: DF.SmallText | None
		max_age_days: DF.Int
		rounding_step: DF.Float
		rule_level: DF.Literal["Warn", "Off", "Block"]
		rules: DF.Table[SPPriceRule]
	# end: auto-generated types

	def validate(self):
		if self.max_age_days and self.amber_after_days and self.amber_after_days >= self.max_age_days:
			frappe.throw(_("Amber After must be fewer days than the Max Price Age."))
		for fieldname in ("max_age_days", "amber_after_days", "rounding_step"):
			if (self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(self.meta.get_label(fieldname))))
		self.validate_rules()

	def validate_rules(self):
		"""One rule per price, never from itself, and no loop (BTB from BTC and BTC from BTB)."""
		depends_on = {}
		for row in self.rules:
			target, base = RULE_TARGET[row.target], RULE_BASE[row.base]
			if target == base:
				frappe.throw(_("Row {0}: a price cannot be worked out from itself.").format(row.idx))
			if target in depends_on:
				frappe.throw(_("Row {0}: {1} already has a rule.").format(row.idx, _(row.target)))
			depends_on[target] = base
		for start in depends_on:
			seen, key = set(), start
			while key in depends_on:
				if key in seen:
					frappe.throw(
						_(
							"The pricing rules go round in a circle. Work one price out from the list price or the cost."
						)
					)
				seen.add(key)
				key = depends_on[key]
