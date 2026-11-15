"""A station (SP-73): each won deal becomes a station with a number, owners and live money.

Execution, purchasing and collection all hang on this one record. A station:
- is numbered by year (2027-001, the yearly series of X8);
- opens with an ERPNext Project of the same number (its accounting dimension) and a site
  warehouse under the Sites group (SP-28), and makes its customer featured;
- takes from its case the customer, the accepted quote, the systems, the place and the sales
  owner (the follow-up owner, fixed once the contract exists); the execution owner opens it and
  is also the collection owner until the admin moves collection to someone else;
- moves Open → Purchasing → Installing → Technically closed → Financially closed, or is
  Cancelled (workflow "SP Station"). It is financially closed only when nothing remains: an
  unpaid balance is written off by the admin first (record_write_off).

money.refresh(station) keeps Agreed · Paid (confirmed only) · Remaining · Next due.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, today

from smart_power.sp_stations.station_workflow import CANCELLED, FIN_CLOSED, TECH_CLOSED

STATION, CASE = "SP Station", "SP Case"
PROJECT_MANAGER, ADMIN_ROLES = "SP Project Manager", ("SP Admin", "System Manager")
OWNER_LABELS = {
	"sales_owner": "Follow-up Owner",
	"execution_owner": "Execution Owner",
	"collection_owner": "Collection Owner",
}


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def before_insert(doc) -> None:
	"""Fill the station from its case, and set the first owners."""
	if doc.case:
		case = frappe.get_doc(CASE, doc.case)
		doc.customer = doc.customer or case.customer
		doc.quotation_accepted = doc.quotation_accepted or case.accepted_quotation
		doc.sales_owner = doc.sales_owner or case.follow_up_owner
		doc.location_text = doc.location_text or case.location_text
		doc.geo = doc.geo or case.get("geo")
		if not doc.systems:
			for row in case.system_types:
				doc.append("systems", {"system_type": row.system_type, "qty": 1})
	if doc.customer and not doc.region:
		doc.region = frappe.db.get_value("Customer", doc.customer, "sp_region")
	doc.company = (
		doc.company
		or frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)
	if not doc.execution_owner and PROJECT_MANAGER in frappe.get_roles():
		doc.execution_owner = frappe.session.user
	doc.collection_owner = doc.collection_owner or doc.execution_owner
	for fieldname, label in OWNER_LABELS.items():
		if doc.get(fieldname):
			doc.append(
				"owner_history",
				{
					"role_kind": label,
					"to_user": doc.get(fieldname),
					"from_date": now_datetime(),
					"reason": _("Station opened"),
					"changed_by": frappe.session.user,
				},
			)


def after_insert(doc) -> None:
	"""The station's Project (its accounting dimension), its site warehouse, a featured customer."""
	from smart_power.sp_sales.customer import mark_featured
	from smart_power.sp_stock.warehouses import site_warehouse

	project = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": doc.name,
			"company": doc.company,
			"customer": doc.customer,
			"status": "Open",
		}
	)
	project.flags.ignore_permissions = True
	project.insert()
	doc.db_set("project", project.name)
	doc.db_set("site_warehouse", site_warehouse(project.name))
	if doc.customer:
		mark_featured(doc.customer)
	from smart_power.sp_stations.money import refresh

	refresh(doc.name)


def validate(doc) -> None:
	if doc.customer:  # the customer may come from the case, after the form's own fetch
		doc.customer_name = frappe.db.get_value("Customer", doc.customer, "customer_name")
	doc.capacity_kw_total = sum(flt(r.capacity_kw) * (flt(r.qty) or 1) for r in doc.systems)
	if doc.is_new():
		return
	before = doc.get_doc_before_save()
	if (
		before
		and before.sales_order
		and before.sales_owner != doc.sales_owner
		and not doc.flags.sp_owner_change_reason
	):
		frappe.throw(_("The sales owner is fixed once the contract exists."))
	_record_owner_changes(doc, before)
	if before and before.status != doc.status:
		if doc.status == TECH_CLOSED and not doc.tech_closed_on:
			doc.tech_closed_on = today()
		if doc.status == FIN_CLOSED:
			if flt(doc.remaining_amount) > 0:
				frappe.throw(
					_(
						"Station {0} still has {1} to collect. Collect it, or the admin records a write-off, before the financial close."
					).format(doc.name, frappe.format(doc.remaining_amount, "Currency")),
					title=_("Money remaining"),
				)
			doc.fin_closed_on = doc.fin_closed_on or today()
		if doc.status == CANCELLED and before.status in (TECH_CLOSED, FIN_CLOSED):
			frappe.throw(_("A closed station cannot be cancelled."))


def _record_owner_changes(doc, before) -> None:
	if not before:
		return
	for fieldname, label in OWNER_LABELS.items():
		old, new = before.get(fieldname), doc.get(fieldname)
		if old == new:
			continue
		if fieldname != "sales_owner" and not is_admin() and old:
			frappe.throw(_("Only the admin changes the {0}.").format(_(label)))
		doc.append(
			"owner_history",
			{
				"role_kind": label,
				"from_user": old,
				"to_user": new,
				"from_date": now_datetime(),
				"reason": doc.flags.sp_owner_change_reason or _("Changed by {0}").format(frappe.session.user),
				"changed_by": frappe.session.user,
			},
		)


@frappe.whitelist(methods=["POST"])
def record_write_off(station: str, amount: float, reason: str) -> dict:
	"""The admin writes off what cannot be collected, so the station can close financially. The
	write-off posts through the Account Map (event Write-off) and is listed for review."""
	from smart_power.sp_core.review_centre import raise_item
	from smart_power.sp_finance.posting import post
	from smart_power.sp_stations.money import refresh

	if not is_admin():
		frappe.throw(_("Only the admin records a write-off."), frappe.PermissionError)
	reason = (reason or "").strip()
	if not reason:
		frappe.throw(_("A write-off needs a reason."), frappe.MandatoryError)
	doc = frappe.get_doc(STATION, station)
	amount = flt(amount)
	if amount <= 0 or amount > flt(doc.remaining_amount):
		frappe.throw(
			_("Write off between 0 and the remaining {0}.").format(
				frappe.format(doc.remaining_amount, "Currency")
			)
		)
	entry = post(
		"Write-off",
		doc,
		amount,
		company=doc.company,
		project=doc.project,
		party_type="Customer",
		party=doc.customer,
		remark=_("Write-off on station {0}: {1}").format(doc.name, reason),
	)
	doc.db_set("write_off_amount", flt(doc.write_off_amount) + amount)
	doc.add_comment("Info", _("Wrote off {0}: {1}").format(frappe.format(amount, "Currency"), reason))
	raise_item(
		"Write-off",
		doc,
		_("Write-off of {0} on station {1}: {2}").format(frappe.format(amount, "Currency"), doc.name, reason),
		amount=amount,
	)
	return {"journal_entry": entry, **refresh(doc.name)}
