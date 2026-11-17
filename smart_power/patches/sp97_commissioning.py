"""SP-97: each system type's commissioning checklist and readings."""


def execute():
	from smart_power.sp_site.commissioning import seed_commissioning_templates

	seed_commissioning_templates()
