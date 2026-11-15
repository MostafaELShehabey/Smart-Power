"""Station setup (SP-175)."""

import frappe


def enable_stock_reservation() -> None:
	"""Stock is reserved against the Sales Order from the deposit (tech plan section 3 rule 8), so
	Stock Settings > Enable Stock Reservation is turned on, once (install and patch); partial
	reservations are allowed, since part of an order is often in stock. The admin may change it."""
	settings = frappe.get_single("Stock Settings")
	if settings.enable_stock_reservation:
		return
	settings.enable_stock_reservation = 1
	settings.allow_partial_reservation = 1
	settings.flags.ignore_mandatory = True
	settings.flags.ignore_permissions = True
	settings.save()
