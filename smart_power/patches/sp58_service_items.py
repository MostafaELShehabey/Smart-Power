"""SP-58: the service items of the special quote lines (manual, winch, commission)."""


def execute():
	from smart_power.sp_quotes.special_lines import seed_service_items

	seed_service_items()
