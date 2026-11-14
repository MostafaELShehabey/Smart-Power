"""SP-62: the quote print format Smart Power sends (once, if the setting is empty)."""

from smart_power.sp_quotes.quote_print import seed_default_print_format


def execute():
	seed_default_print_format()
