"""SP-178: the iron weight variance warning (2%), seeded where it is empty."""


def execute():
	from smart_power.sp_core.setup.seed import seed_settings

	seed_settings()
