"""Postal cheque register (A5, SP-118; journey J8): every cheque and who physically holds it.

    Received → Due → Deposited → Collected;  side exits: Bounced → With lawyer

- A cheque is logged with the contract (D1: its cheque rows become cheques when the contract is
  submitted) or later, with its no., amount, due date, bank or post office and holder.
- Daily (check_due): a cheque becomes Due `Cheque Due Alert` days before its due date; its holder,
  the station's collection owner and the admin are alerted.
- Deposited: taken to the Post. Collected: a customer payment by postal cheque into The Post is
  made and (Confirm Collected Cheques at Once) posted, so it counts on the station.
- Bounced: a collected cheque's payment is cancelled, which reverses its entry; the station owes
  it again (its next due instalment overdue); the collection owner and the admin are told.
  With lawyer can follow; the lawyer's work stays outside the system.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

CHEQUE, STATION, PAYMENT = "SP Cheque", "SP Station", "SP Customer Payment"
RECEIVED, DUE, DEPOSITED, COLLECTED, BOUNCED, WITH_LAWYER = (
	"Received",
	"Due",
	"Deposited",
	"Collected",
	"Bounced",
	"With lawyer",
)
POSTAL_CHEQUE = "Payment Method-POSTAL_CHEQUE"
ADMIN_ROLE = "SP Admin"
# what each action may follow
MOVES = {
	DEPOSITED: (RECEIVED, DUE),
	COLLECTED: (RECEIVED, DUE, DEPOSITED),
	BOUNCED: (RECEIVED, DUE, DEPOSITED, COLLECTED),
	WITH_LAWYER: (BOUNCED,),
}


def validate(doc) -> None:
	if flt(doc.amount) <= 0:
		frappe.throw(_("The amount must be above zero."))
	station = frappe.db.get_value(
		STATION, doc.station, ["customer", "customer_name", "company", "sales_order"], as_dict=True
	)
	if station:
		doc.customer, doc.customer_name = station.customer, station.customer_name
		doc.company = station.company
		doc.sales_order = doc.sales_order or station.sales_order
	duplicate = frappe.db.get_value(
		CHEQUE,
		{"cheque_no": doc.cheque_no, "bank_or_post": doc.bank_or_post or "", "name": ("!=", doc.name)},
	)
	if duplicate:
		frappe.throw(_("Cheque {0} is already registered as {1}.").format(doc.cheque_no, duplicate))


def _move(name: str, to: str):
	doc = frappe.get_doc(CHEQUE, name)
	doc.check_permission("write")
	if doc.status not in MOVES[to]:
		frappe.throw(
			_("Cheque {0} is {1}; it cannot become {2}.").format(doc.cheque_no, _(doc.status), _(to))
		)
	return doc


@frappe.whitelist(methods=["POST"])
def mark_deposited(name: str) -> str:
	doc = _move(name, DEPOSITED)
	doc.status, doc.deposited_on = DEPOSITED, today()
	doc.save()
	return doc.status


@frappe.whitelist(methods=["POST"])
def mark_collected(name: str) -> str:
	"""The money is in: a postal-cheque payment into The Post, posted (or pending, per settings)."""
	from smart_power.sp_core.services.settings import get_value
	from smart_power.sp_finance.customer_payment import post_confirmed

	doc = _move(name, COLLECTED)
	payment = frappe.get_doc(
		{
			"doctype": PAYMENT,
			"station": doc.station,
			"amount": flt(doc.amount),
			"work_date": today(),
			"method": POSTAL_CHEQUE,
			"receiving_account": _post_account(doc.company),
			"reference_no": doc.cheque_no,
			"cheque": doc.name,
		}
	)
	payment.flags.ignore_permissions = True
	payment.insert()
	payment.submit()
	if cint(get_value("cheque_auto_confirm")):
		post_confirmed(frappe.get_doc(PAYMENT, payment.name))
	doc.status, doc.collected_on, doc.customer_payment = COLLECTED, today(), payment.name
	doc.save()
	return doc.status


def _post_account(company: str) -> str:
	"""The Postal Cheque mode's account (The Post, SP-26)."""
	account = frappe.db.get_value(
		"Mode of Payment Account", {"parent": "Postal Cheque", "company": company}, "default_account"
	) or frappe.db.get_value("Account", {"company": company, "account_name": "The Post", "is_group": 0})
	if not account:
		frappe.throw(_("Set the Postal Cheque account of {0} (Mode of Payment).").format(company))
	return account


@frappe.whitelist(methods=["POST"])
def mark_bounced(name: str, note: str | None = None) -> str:
	"""Returned unpaid: a collected cheque's payment is reversed and the station owes it again."""
	doc = _move(name, BOUNCED)
	if doc.customer_payment:
		payment = frappe.get_doc(PAYMENT, doc.customer_payment)
		if payment.docstatus == 1:
			payment.flags.ignore_permissions = True
			payment.cancel()  # cancels its Payment Entry: the reversal posts
	doc.status, doc.bounced_on = BOUNCED, today()
	if note:
		doc.notes = "\n".join(part for part in (doc.notes, note) if part)
	doc.save()
	from smart_power.sp_stations.money import refresh

	refresh(doc.station)
	owner = frappe.db.get_value(STATION, doc.station, "collection_owner")
	_alert(
		doc,
		[owner, *_admins()],
		_("Cheque {0} of {1} bounced ({2})").format(
			doc.cheque_no, frappe.format(doc.amount, "Currency"), doc.customer_name or doc.station
		),
	)
	return doc.status


@frappe.whitelist(methods=["POST"])
def mark_with_lawyer(name: str) -> str:
	doc = _move(name, WITH_LAWYER)
	doc.status = WITH_LAWYER
	doc.save()
	return doc.status


# --- the daily due check -------------------------------------------------------------------------


def check_due() -> list[str]:
	"""Received cheques whose due date is within the lead days become Due, with an alert."""
	from smart_power.sp_core.services.settings import get_value

	lead = cint(get_value("cheque_due_lead_days"))
	limit = add_days(today(), lead)
	made_due = []
	for name in frappe.get_all(CHEQUE, {"status": RECEIVED, "due_date": ("<=", limit)}, pluck="name"):
		doc = frappe.get_doc(CHEQUE, name)
		doc.status = DUE
		doc.save(ignore_permissions=True)
		owner = frappe.db.get_value(STATION, doc.station, "collection_owner")
		_alert(
			doc,
			[doc.holder, owner, *_admins()],
			_("Cheque {0} of {1} is due on {2}; deposit it at the Post").format(
				doc.cheque_no,
				frappe.format(doc.amount, "Currency"),
				frappe.format(getdate(doc.due_date), "Date"),
			),
		)
		made_due.append(name)
	return made_due


def _admins() -> list[str]:
	from smart_power.sp_sales.quote_request import _users_with

	return _users_with(ADMIN_ROLE)


def _alert(doc, users, subject: str) -> None:
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	users = sorted({u for u in users if u})
	if users:
		make_notification_logs(
			frappe._dict(
				{
					"type": "Alert",
					"document_type": CHEQUE,
					"document_name": doc.name,
					"subject": subject,
					"from_user": frappe.session.user,
				}
			),
			users,
		)


# --- the contract's cheques (D1) and the home lists --------------------------------------------------


def from_contract(so, method=None) -> None:
	"""Sales Order on_submit: each cheque row of the contract becomes a cheque in the register."""
	if not so.get("sp_station"):
		return
	for row in so.get("sp_cheques") or []:
		if frappe.db.exists(CHEQUE, {"cheque_no": row.cheque_no, "bank_or_post": row.bank or ""}):
			continue
		frappe.get_doc(
			{
				"doctype": CHEQUE,
				"cheque_no": row.cheque_no,
				"amount": row.amount,
				"due_date": row.due_date,
				"bank_or_post": row.bank,
				"holder": row.holder,
				"station": so.sp_station,
				"sales_order": so.name,
				"notes": row.note,
			}
		).insert(ignore_permissions=True)


@frappe.whitelist()
def home_lists() -> dict:
	"""Cheques due this week and bounced cheques, for the Finance and Projects home pages."""
	fields = ["name", "cheque_no", "amount", "due_date", "customer_name", "station", "holder", "status"]
	week = add_days(today(), 7)  # sp-allow-number: a week
	return {
		"due_this_week": frappe.get_list(
			CHEQUE,
			{"status": ("in", (RECEIVED, DUE, DEPOSITED)), "due_date": ("<=", week)},
			fields,
			order_by="due_date asc",
		),
		"bounced": frappe.get_list(CHEQUE, {"status": BOUNCED}, fields, order_by="bounced_on desc"),
	}
