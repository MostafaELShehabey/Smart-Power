"""The 24 h quote clock (SP-48, decision 70: a warning, never a block).

A quote request should get its quote within Quote Due Within hours (Smart Power Settings,
24). The clock runs from the request until the case is Sent to customer (SP-61 will stop
it when a quote version is sent). It is amber after Quote Amber After hours (18) and
overdue after Quote Due Within.
"""

from frappe.utils import add_to_date, get_datetime, now_datetime

from smart_power.sp_core.services.settings import get_value

ON_TIME, AMBER, OVERDUE, SENT = "On time", "Amber", "Overdue", "Sent"
SENT_STATUS = "Sent to customer"
SECONDS_PER_HOUR = 3600  # sp-allow-number: unit conversion, not a business value


def due_hours() -> float:
	return float(get_value("quote_due_hours", 0) or 0)


def amber_hours() -> float:
	return float(get_value("quote_amber_hours", 0) or 0)


def due_at(start) -> str | None:
	"""When the quote is due for a request made at `start` (None if no limit is set)."""
	hours = due_hours()
	return add_to_date(get_datetime(start), hours=hours) if hours else None


def clock(case, now=None) -> dict:
	"""Hours since the request, and On time / Amber / Overdue (or Sent when the clock stopped).

	case: an SP Case document or a dict with creation and quote_sent_at.
	"""
	start = get_datetime(case.get("creation"))
	stopped = case.get("quote_sent_at")
	end = get_datetime(stopped) if stopped else get_datetime(now or now_datetime())
	hours = max((end - start).total_seconds(), 0) / SECONDS_PER_HOUR
	if stopped:
		state = SENT
	elif due_hours() and hours >= due_hours():
		state = OVERDUE
	elif amber_hours() and hours >= amber_hours():
		state = AMBER
	else:
		state = ON_TIME
	return {"hours": round(hours, 1), "state": state}


def on_validate(doc) -> None:
	"""Set the due time when the case opens; stop the clock when it is sent to the customer."""
	if doc.is_new():
		doc.quote_due_at = due_at(doc.get("creation") or now_datetime())
	if doc.status == SENT_STATUS and not doc.quote_sent_at:
		doc.quote_sent_at = now_datetime()
