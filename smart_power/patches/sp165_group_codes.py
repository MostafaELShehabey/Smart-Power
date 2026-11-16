"""SP-165: the code prefix and required specs of the catalogue item groups (where still empty)."""


def execute():
	from smart_power.sp_stock.item_codes import seed_group_codes

	seed_group_codes()
