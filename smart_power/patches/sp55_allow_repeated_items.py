"""SP-55: let one item appear on more than one line of a quote (once; then the admin's)."""

from smart_power.sp_sales.setup import allow_repeated_items


def execute():
	allow_repeated_items()
