"""Price check only (SP-49, IP1): an enquiry that ends at the indicative price.

    close_price_check(request) -> {case, customer}

The enquiry is kept as an SP Case, closed as Lost with the reason "Price check only", so it
counts in the conversion report (R6) and in AD1 "lost as price check only". The case holds
the indicative price that was given (value, date, specs, who ran it). The customer is
optional: with a mobile the returning customer is linked, or a new one is made when a name is
given too; otherwise the name and mobile (if any) stay on the case only. A colleague's
customer is not linked, so the price check never changes who follows them up.
No task and no notification: nothing is left to do on a price check.
"""

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import cstr

from smart_power.sp_quotes.indicative import recall, record_on_case
from smart_power.sp_sales.case import price_check_reason
from smart_power.sp_sales.customer import find_by_mobile, is_valid_mobile, normalize_mobile
from smart_power.sp_sales.quote_request import COLLEAGUE, customer_status

CASE = "SP Case"
CHANNELS = ("Showroom", "Call", "Marketing")
# the roles that may close a case as lost (the SP Case workflow's Mark Lost)
CLOSING_ROLES = ("SP Customer Followup", "SP Admin")
MARK_LOST = "Mark Lost"


@frappe.whitelist(methods=["POST"])
def close_price_check(request: dict | str) -> dict:
	"""request: run (the indicative price shown), channel, and optionally mobile,
	customer_name, tier, region and note."""
	frappe.has_permission(CASE, "create", throw=True)
	request = frappe._dict(frappe.parse_json(request) if isinstance(request, str) else request)
	if frappe.session.user != "Administrator" and not set(CLOSING_ROLES) & set(frappe.get_roles()):
		frappe.throw(
			_("Only a follow-up user can close a price check. Make a quote request instead."),
			frappe.PermissionError,
		)
	run = recall(request.get("run"))
	if not run:
		frappe.throw(_("Calculate the indicative price first."), frappe.MandatoryError)
	if request.get("channel") not in CHANNELS:
		frappe.throw(_("Choose the channel."), frappe.MandatoryError)
	reason = price_check_reason()
	if not reason:
		frappe.throw(
			_("The lost reason {0} is missing or inactive.").format(frappe.bold(_("Price check only")))
		)

	name = cstr(request.get("customer_name")).strip()
	mobile = normalize_mobile(request.get("mobile")) if request.get("mobile") else ""
	if mobile and not is_valid_mobile(mobile):
		frappe.throw(_("{0} is not a valid Egyptian mobile.").format(frappe.bold(request.get("mobile"))))

	frappe.db.savepoint("sp_price_check")
	try:
		existing = find_by_mobile(mobile) if mobile else None
		customer = existing if existing and customer_status(existing)[0] != COLLEAGUE else None
		if not existing and mobile and name:
			customer = (
				frappe.get_doc(
					{
						"doctype": "Customer",
						"customer_name": name,
						"sp_mobile": mobile,
						"sp_tier": request.get("tier") or None,
						"sp_region": request.get("region") or None,
					}
				)
				.insert()
				.name
			)
		case = frappe.get_doc(
			{
				"doctype": CASE,
				"customer": customer,
				"customer_name": None if customer else name or None,
				"mobile": None if customer else mobile or None,
				"channel": request.channel,
				"requested_by": frappe.session.user,
				"follow_up_owner": frappe.session.user,
				"system_types": [{"system_type": run.system_type}],
				"lost_reason": reason,
				"lost_note": cstr(request.get("note")).strip() or None,
			}
		)
		record_on_case(case, request.run)
		case.insert()
		apply_workflow(case, MARK_LOST)
	except Exception:
		frappe.db.rollback(save_point="sp_price_check")
		raise
	return {"case": case.name, "customer": customer}
