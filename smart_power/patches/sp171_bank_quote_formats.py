"""SP-171: the Al-Ahly and Agri Bank quote formats, once each (the admin owns them afterwards)."""


def execute():
	from smart_power.sp_quotes.bank_formats import seed_bank_formats

	seed_bank_formats()
