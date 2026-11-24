"""stations.mine / stations.get (SP-148): the site view of a station. No money ever: no price,
cost, amount or payment field is sent, whoever asks. The station's own row rules decide who reads
which station (SP-35)."""

import frappe
from frappe import _

from smart_power.api.mobile.v1.common import endpoint, fail, safe

STATION = "SP Station"
FIELDS = (
	"name",
	"customer_name",
	"status",
	"systems_summary",
	"capacity_kw_total",
	"hp_total",
	"location_text",
	"geo",
	"region",
	"execution_owner",
	"site_receiver",
	"operation_date",
	"winch_status",
	"modified",
)
SYSTEM_FIELDS = ("system_type", "capacity_kw", "qty")
PAGE = 200  # sp-allow-number: stations a phone lists at once, more than anyone is on


def _station_rows(filters: dict) -> list[dict]:
	if not frappe.has_permission(STATION, "read"):
		return []
	return safe(
		frappe.get_list(
			STATION, filters=filters, fields=list(FIELDS), order_by="modified desc", limit_page_length=PAGE
		)
	)


@endpoint(methods=("GET",))
def mine() -> list[dict]:
	return _station_rows({"status": ("not in", ("Financially closed", "Cancelled"))})


@endpoint(methods=("GET",))
def get(name: str) -> dict:
	if not frappe.db.exists(STATION, name):
		fail("NOT_FOUND", _("Station {0} was not found.").format(name))
	if not frappe.has_permission(STATION, "read", doc=name):
		fail("NOT_PERMITTED", _("You are not on this station."))
	doc = frappe.get_doc(STATION, name)
	from smart_power.sp_site.site_tasks import board

	return safe(
		{
			**{f: doc.get(f) for f in FIELDS},
			"systems": [{f: r.get(f) for f in SYSTEM_FIELDS} for r in doc.systems],
			"customer_mobile": frappe.db.get_value("Customer", doc.customer, "sp_mobile")
			if doc.customer
			else None,
			"tasks": board(name),
		}
	)
