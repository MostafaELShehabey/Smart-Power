"""SP-56: the pump calculation template (energy + submersible), published for pump quotes."""

from smart_power.sp_quotes.calc_templates import seed_calc_templates
from smart_power.sp_stock.item import seed_item_groups


def execute():
	seed_item_groups()  # the groups its lines pick from (seeds the template too)
	seed_calc_templates()
