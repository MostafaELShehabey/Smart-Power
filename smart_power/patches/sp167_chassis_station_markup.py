"""SP-167: the setting "Chassis Markup in Station Offers", seeded where it is empty."""


def execute():
	from smart_power.sp_core.setup.seed import seed_settings

	seed_settings()
