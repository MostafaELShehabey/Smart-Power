"""SP-22: money format and login branding on sites installed before they were added."""

from smart_power.sp_core.setup.locale import apply_branding, apply_currency


def execute():
	apply_currency()
	apply_branding()
