"""SP-31: number new customers CUS-##### on sites installed before this change."""

from smart_power.sp_sales.setup import apply_customer_naming


def execute():
	apply_customer_naming()
