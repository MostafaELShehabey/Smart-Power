"""SP-114: the payment method "paid to a third party" (a list value the admin can rename)."""

from smart_power.sp_core.setup.seed import seed_list_values


def execute():
	seed_list_values()
