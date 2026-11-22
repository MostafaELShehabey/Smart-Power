"""SP-125: Sales Invoice's default series is the internal SINV-.YYYY.-.####."""


def execute():
	from smart_power.sp_finance.invoices import ensure_default_series

	ensure_default_series()
