"""SP-171: the banks' quote formats move from the classic print format builder (removed in Frappe 17)
to the new one, keeping the admin's changes and the printed sheet."""


def execute():
	from smart_power.sp_quotes.bank_formats import convert_to_new_builder

	convert_to_new_builder()
