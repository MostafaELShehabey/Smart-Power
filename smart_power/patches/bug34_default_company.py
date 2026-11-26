"""BUG-34: sites set up before the company was made get it as the desk's default company."""

from smart_power.sp_core.setup.company import ensure_default_company


def execute():
	ensure_default_company()
