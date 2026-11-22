"""SP-172: the off-grid calculation template, published for off-grid quotes when none is."""

from smart_power.sp_quotes.calc_templates import seed_calc_templates
from smart_power.sp_stock.item import seed_item_groups


def execute():
	seed_item_groups()  # the groups its lines pick from (seeds the templates too)
	seed_calc_templates()
