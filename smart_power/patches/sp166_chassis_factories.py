"""SP-166: the Agri Solar and Ali El-Shafei chassis factories, once each (the admin owns them)."""


def execute():
	from smart_power.sp_quotes.chassis_calc import seed_factories

	seed_factories()
