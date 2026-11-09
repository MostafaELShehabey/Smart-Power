"""SP-32: add the list values the story names to sites installed before them (by list and code)."""

from smart_power.sp_core.setup.seed import seed_list_values


def execute():
	seed_list_values()
