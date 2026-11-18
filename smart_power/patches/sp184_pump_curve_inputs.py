"""SP-184: the pump template asks for the required head and flow, in a new published version."""

from smart_power.sp_quotes.calc_templates import add_curve_inputs


def execute():
	add_curve_inputs()
