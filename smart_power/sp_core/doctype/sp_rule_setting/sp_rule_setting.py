# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class SPRuleSetting(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		applies_to: DF.Data | None
		category: DF.Literal["Commercial", "Technical"]
		description: DF.SmallText | None
		events: DF.Data | None
		fired_30d: DF.Int
		level: DF.Literal["Off", "Warn", "Block"]
		limits: DF.Code | None
		never_block: DF.Check
		rule_key: DF.Data
		scope_doctype: DF.Link | None
		scope_offer_type: DF.Link | None
		title: DF.Data | None
		warn_needs_reason: DF.Check
	# end: auto-generated types

	def validate(self):
		if self.never_block and self.level == "Block":
			frappe.throw(_("This rule can only warn; it can never block (decisions 47 and 67)."))
		if self.limits:
			try:
				value = json.loads(self.limits)
			except ValueError:
				frappe.throw(_("Limits must be valid JSON."))
			if not isinstance(value, dict):
				frappe.throw(_('Limits must be a JSON object, for example {"max_days": 3}.'))

	def on_update(self):
		from smart_power.rules import clear_cache

		clear_cache()
