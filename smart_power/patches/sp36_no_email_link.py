"""SP-36: no login by email link: a forgotten password goes through the admin, never an email."""


def execute():
	from smart_power.sp_core.login import apply_login_settings

	apply_login_settings()
