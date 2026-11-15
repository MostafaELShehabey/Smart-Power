"""SP-73: the SP Station workflow's states and actions, before the workflow fixture loads."""

from smart_power.sp_stations.station_workflow import ensure_workflow_masters


def execute():
	ensure_workflow_masters()
