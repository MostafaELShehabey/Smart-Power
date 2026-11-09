"""Display formats shared by the desk, print formats and PDFs (SP-22).

Frappe stores and edits times on a 24-hour clock. Smart Power shows them on a 12-hour clock with
ص/م (AM/PM in English). Only the display changes; stored values stay 24 h.
"""

from frappe import _
from frappe.utils import format_date, get_datetime, get_time


def time_12h(value) -> str:
	"""09:05 → "09:05 ص", 21:30 → "09:30 م"; empty for no value."""
	if not value:
		return ""
	t = get_time(value)
	return f"{t.strftime('%I:%M')} {_(t.strftime('%p'))}"


def datetime_12h(value) -> str:
	"""A datetime in the site's date format with a 12-hour time, e.g. "09-11-2026 09:30 م"."""
	if not value:
		return ""
	dt = get_datetime(value)
	return f"{format_date(dt)} {time_12h(dt)}"
