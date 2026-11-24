# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class SmartPowerSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from smart_power.sp_core.doctype.sp_account_map.sp_account_map import SPAccountMap
		from smart_power.sp_core.doctype.sp_brand_priority.sp_brand_priority import SPBrandPriority
		from smart_power.sp_core.doctype.sp_margin_range.sp_margin_range import SPMarginRange

		account_map: DF.Table[SPAccountMap]
		brand_priorities: DF.Table[SPBrandPriority]
		btb_price_list: DF.Link | None
		btc_price_list: DF.Link | None
		calibration_min_stations: DF.Int
		case_inactivity_days: DF.Int
		chassis_iron_markup_pct: DF.Percent
		chassis_markup_basis: DF.Literal["Markup on cost", "Margin on sale"]
		cost_of_money_pct: DF.Percent
		cost_price_list: DF.Link | None
		creator_discount_max_pct: DF.Percent
		default_quote_print_format: DF.Link | None
		default_rounding_step: DF.Float
		field_entry_lock_days: DF.Int
		followup_delay_days: DF.Int
		followup_discount_max_pct: DF.Percent
		list_price_list: DF.Link | None
		margin_ranges: DF.Table[SPMarginRange]
		max_validity_days: DF.Int
		mobile_rate_limit: DF.Int
		oil_alert_km: DF.Int
		oil_interval_km: DF.Int
		quote_amber_hours: DF.Int
		quote_due_hours: DF.Int
		showroom_cash_limit_amount: DF.Currency
		showroom_cash_limit_days: DF.Int
		validity_days: DF.Int
		winch_debt_age_months: DF.Int
	# end: auto-generated types

	def validate(self):
		for row in self.margin_ranges:
			if flt(row.min_pct) > flt(row.max_pct):
				frappe.throw(
					_("Row {0}: the minimum margin is higher than the maximum.").format(row.idx),
					title=_("Margin Ranges"),
				)
		seen = set()
		for row in self.brand_priorities:
			key = (row.item_group, row.brand)
			if key in seen:
				frappe.throw(
					_("Row {0}: {1} is listed twice for {2}.").format(row.idx, row.brand, row.item_group)
				)
			seen.add(key)
		for df in self.meta.fields:
			if df.fieldtype in ("Int", "Float", "Percent", "Currency") and flt(self.get(df.fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(df.label)))
