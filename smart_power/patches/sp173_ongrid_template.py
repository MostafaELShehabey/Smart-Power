"""SP-173: the on-grid calculation template and the grid-connection task template."""

from smart_power.sp_quotes.calc_templates import seed_calc_templates
from smart_power.sp_stations.task_templates import seed_task_templates
from smart_power.sp_stock.item import seed_item_groups


def execute():
	seed_item_groups()  # the groups its lines pick from (seeds the calc templates too)
	seed_calc_templates()
	seed_task_templates()
