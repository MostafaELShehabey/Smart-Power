"""SP-29: add the catalogue item groups to sites set up before this change."""

from smart_power.sp_stock.item import seed_item_groups


def execute():
	seed_item_groups()
