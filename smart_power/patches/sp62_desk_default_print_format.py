"""SP-62: quotes open with SP Quotation in the desk, once, unless the admin built their own
format (decided by the user on 2026-11-14)."""

from smart_power.sp_quotes.quote_print import make_desk_default


def execute():
	make_desk_default()
