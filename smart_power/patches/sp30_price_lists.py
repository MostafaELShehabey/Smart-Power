"""SP-30: add the four price lists and the price categories to sites set up before this change."""

from smart_power.sp_stock.prices import seed_price_categories, seed_price_lists


def execute():
	seed_price_lists()
	seed_price_categories()
