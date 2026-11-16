"""SP-49: the "Price Check Only" workflow action exists before the SP Case workflow fixture syncs."""

from smart_power.sp_sales.case_workflow import ensure_workflow_masters


def execute():
	ensure_workflow_masters()
