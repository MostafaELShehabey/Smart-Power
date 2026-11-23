"""SP-99: the "Out-of-warranty service charge" simple record type, on sites installed before it
(the list values are seeded at install; the seed adds only what is missing)."""

from smart_power.sp_core.setup.seed import seed_list_values


def execute():
	seed_list_values()
