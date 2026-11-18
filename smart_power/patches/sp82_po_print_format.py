"""SP-82: the purchase order prints in Smart Power's format, unless the admin chose their own."""

import frappe

from smart_power.sp_stock.po_print import make_desk_default


def execute():
	frappe.reload_doc("sp_stock", "print_format", "sp_purchase_order")
	make_desk_default()
