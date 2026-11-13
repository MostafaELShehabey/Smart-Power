"""SP-46: the SP Case workflow states and actions, created before fixtures sync the workflow."""

from smart_power.sp_sales.case_workflow import ensure_workflow_masters


def execute():
	ensure_workflow_masters()
