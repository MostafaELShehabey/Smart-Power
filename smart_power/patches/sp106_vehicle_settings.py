"""SP-106: the oil change defaults, on sites made before they existed."""

from smart_power.sp_core.setup.seed import seed_settings


def execute():
	seed_settings()
