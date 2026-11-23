"""bookings.today (SP-148): the driver's winch jobs of today."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe


@endpoint(methods=("GET",))
def today() -> list[dict]:
	from smart_power.sp_winch.bookings import todays_jobs

	return todays_jobs()
