"""SP-47: give each system type its quote request fields on sites set up before this change."""

from smart_power.sp_sales.quote_request import seed_request_fields


def execute():
	seed_request_fields()
