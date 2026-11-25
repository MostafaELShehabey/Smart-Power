"""Notifications G4 (SP-40): the in-app feed is the official channel for requests, approvals and
alerts (decision 70: WhatsApp stays allowed, the record is here).

    send(event, users, doctype, name, subject)   # subject: a text, or lambda: _(...) per reader

1. an in-app item for each user (Frappe's Notification Log, the bell), tagged with its event;
2. the users' unread count in realtime (`sp_counts`);
3. a push to the phone for the users who want it for that event (their preference, else the
   event's default). Push senders plug in through the `sp_push_senders` hook (the Flutter app's
   FCM, SP-149), each called as fn(user, event_key, subject, doctype, docname); until then
   nothing is pushed.

The event catalogue (SP Notification Event) is the developer's, synced from the seed on
migrate; each user's per-event choice is a row of their Notification Preferences (User).
"""

import frappe
from frappe import _

EVENT, PREF, LOG = "SP Notification Event", "SP User Notification Pref", "Notification Log"


def sync_events() -> None:
	"""The catalogue from the seed: new events are added; labels and roles follow the code; the
	admin's push default is kept."""
	from smart_power.sp_core.setup.seed import defaults

	for row in defaults().get("notification_events", []):
		values = {"label_ar": row["label_ar"], "label_en": row.get("label_en"), "roles": row.get("roles")}
		if frappe.db.exists(EVENT, row["key"]):
			frappe.db.set_value(EVENT, row["key"], values, update_modified=False)
		else:
			frappe.get_doc(
				{"doctype": EVENT, "key": row["key"], "default_push": row.get("default_push", 0), **values}
			).insert(ignore_permissions=True)


def wants_push(user: str, event: str) -> bool:
	"""The user's own choice for the event, else the event's default."""
	choice = frappe.db.get_value(PREF, {"parent": user, "parenttype": "User", "event": event}, "push")
	if choice is not None:
		return bool(choice)
	return bool(frappe.db.get_value(EVENT, event, "default_push"))


def unread(user: str) -> int:
	return frappe.db.count(LOG, {"for_user": user, "read": 0})


def by_language(users) -> dict[str, list[str]]:
	"""The users by their own language (else the site's). A daily job has no reader of its own, so
	what it writes for people is written once per language (BUG-22)."""
	default = frappe.db.get_single_value("System Settings", "language") or "ar"
	groups: dict[str, list[str]] = {}
	for user in frappe.get_all("User", {"name": ("in", list(users) or [""])}, ["name", "language"]):
		groups.setdefault(user.language or default, []).append(user.name)
	return groups


def language_of(user: str) -> str:
	return next(iter(by_language([user])), None) or frappe.local.lang


def render(subject, lang: str) -> str:
	"""A subject in one language: a function is called in that language; a text is as it is."""
	if not callable(subject):
		return subject
	from frappe.translate import print_language

	with print_language(lang):
		return subject()


def send(
	event: str, users, doctype: str | None, name: str | None, subject, from_user: str | None = None
) -> dict:
	"""Notify the users of an event; returns who got it in the app and who was pushed.

	subject: the text, or a function that builds it (`lambda: _("…").format(…)`). A function is
	called in each reader's own language, so a scheduled job, which runs in the site's language,
	still writes to every reader in theirs (BUG-22)."""
	from frappe.desk.doctype.notification_log.notification_log import make_notification_logs

	if not frappe.db.exists(EVENT, event):
		frappe.throw(_("Unknown notification event {0}.").format(frappe.bold(event)))
	users = sorted({u for u in users or [] if u and u != "Guest"})
	if not users:
		return {"in_app": [], "push": []}
	groups = by_language(users) if callable(subject) else {frappe.local.lang: users}
	texts = {}
	for lang, group in groups.items():
		text = render(subject, lang)
		texts.update(dict.fromkeys(group, text))
		make_notification_logs(
			frappe._dict(
				{
					"type": "Alert",
					"document_type": doctype,
					"document_name": name,
					"subject": text,
					"sp_event": event,
					"from_user": from_user or frappe.session.user,
				}
			),
			group,
		)
	for user in users:
		frappe.publish_realtime("sp_counts", {"unread": unread(user)}, user=user, after_commit=True)
	pushed = [u for u in users if wants_push(u, event)]
	for fn in frappe.get_hooks("sp_push_senders"):
		for user in pushed:
			frappe.enqueue(
				fn,
				queue="short",
				# frappe.enqueue keeps `event` for itself
				user=user,
				event_key=event,
				subject=texts.get(user, ""),
				doctype=doctype,
				docname=name,
				enqueue_after_commit=True,
				now=frappe.flags.in_test,
			)
	return {"in_app": users, "push": pushed}


# --- G4 ------------------------------------------------------------------------------------------


@frappe.whitelist()
def feed(limit: int = 50) -> dict:  # sp-allow-number: the feed page size
	"""My notifications, unread first, newest first, with each event's label."""
	user = frappe.session.user
	rows = frappe.get_all(
		LOG,
		{"for_user": user},
		["name", "subject", "document_type", "document_name", "read", "creation", "sp_event", "from_user"],
		order_by="read asc, creation desc",
		limit=int(limit),
	)
	labels = {e.name: e for e in frappe.get_all(EVENT, fields=["name", "label_ar", "label_en"])}
	lang = frappe.local.lang or "ar"
	for row in rows:
		event = labels.get(row.sp_event)
		row["event_label"] = (
			(event.label_ar if lang == "ar" else event.label_en or event.label_ar) if event else ""
		)
	return {"items": rows, "unread": unread(user)}


@frappe.whitelist()
def preferences() -> list[dict]:
	"""Every event with my push choice; the events of my roles first."""
	user = frappe.session.user
	mine = set(frappe.get_roles(user))
	chosen = {
		r.event: bool(r.push)
		for r in frappe.get_all(PREF, {"parent": user, "parenttype": "User"}, ["event", "push"])
	}
	lang = frappe.local.lang or "ar"
	out = []
	for e in frappe.get_all(
		EVENT, fields=["name", "label_ar", "label_en", "default_push", "roles"], order_by="key asc"
	):
		roles = {r.strip() for r in (e.roles or "").split(",") if r.strip()}
		out.append(
			{
				"event": e.name,
				"label": e.label_ar if lang == "ar" else e.label_en or e.label_ar,
				"push": chosen.get(e.name, bool(e.default_push)),
				"mine": bool(roles & mine),
			}
		)
	out.sort(key=lambda r: (not r["mine"], r["label"]))
	return out


@frappe.whitelist(methods=["POST"])
def set_push(event: str, push: int | bool) -> bool:
	"""My choice for one event: push to the phone or the in-app feed only."""
	if not frappe.db.exists(EVENT, event):
		frappe.throw(_("Unknown notification event {0}.").format(frappe.bold(event)))
	user = frappe.session.user
	value = 1 if frappe.utils.cint(push) else 0
	row = frappe.db.get_value(PREF, {"parent": user, "parenttype": "User", "event": event})
	if row:
		frappe.db.set_value(PREF, row, "push", value)
	else:
		# the user's own preference row, written without saving the whole User record
		frappe.get_doc(
			{
				"doctype": PREF,
				"parent": user,
				"parenttype": "User",
				"parentfield": "sp_notification_prefs",
				"event": event,
				"in_app": 1,
				"push": value,
			}
		).db_insert()
	return bool(value)
