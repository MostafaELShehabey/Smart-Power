"""SP-134: a first published quote template (once; then the admin's)."""

from smart_power.sp_core.documents import seed_quote_template


def execute():
	seed_quote_template()
