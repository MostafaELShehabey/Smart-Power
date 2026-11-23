# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

from smart_power.sp_core.guides import training_report


def execute(filters=None):
	return training_report(filters or {})
