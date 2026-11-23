"""User guides and training (E17, SP-162): one Arabic guide per person profile, and the record of
who was trained.

- **SP User Guide** (one per profile of the role catalogue): the user's home, menu and screens,
  the tasks step by step (the three top ones on the one-page card, each with its video link), and
  the do's and don'ts. Seeded from setup/user_guides.json; the seed adds only the guides a site
  does not have, so the admin's edits stay. The card is the print format SP Quick Reference Card.
- **Help** (my_guides): a user sees the guides of the profiles their roles cover (every role of
  the profile); the admin sees them all.
- **SP Training Session**: a guide's session, its attendees, and each top task ticked when the
  user did it unaided; a user who attended and did all three is completed, with who observed.
- **SP Training Status** (training_report): every active user, their guides and whether they
  completed a session (the story's acceptance criterion).
"""

import json
import os

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

GUIDE, SESSION = "SP User Guide", "SP Training Session"
ADMIN_ROLES = ("SP Admin", "System Manager")
TOP_TASKS = 3  # sp-allow-number: the story's top three tasks
SEED_FILE = ("setup", "user_guides.json")
WIDE = 220  # sp-allow-number: column width
NAME_WIDTH = 160  # sp-allow-number: column width
CHECK_WIDTH = 90  # sp-allow-number: column width
LINK_WIDTH = 140  # sp-allow-number: column width
DATE_WIDTH = 110  # sp-allow-number: column width


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def _profiles() -> dict:
	from smart_power.sp_core.setup.role_catalogue import PROFILES

	return {p.name: p for p in PROFILES}


def profile_roles(profile: str) -> set[str]:
	"""The SP roles a profile gives (not the ERPNext base roles every desk user may share)."""
	from smart_power.sp_core.setup.role_catalogue import role

	found = _profiles().get(profile)
	return {role(k) for k in found.keys} if found else set()


# --- the guide ------------------------------------------------------------------------------------


def validate_guide(doc) -> None:
	if doc.profile not in _profiles():
		frappe.throw(_("{0} is not a person profile.").format(doc.profile))
	doc.role_keys = ", ".join(sorted(profile_roles(doc.profile)))
	top = [t for t in doc.tasks if t.is_top]
	if len(top) > TOP_TASKS:
		frappe.throw(_("Mark at most {0} top tasks: they are the card's.").format(TOP_TASKS))


def seed_guides() -> int:
	"""The guides a site does not have yet (by profile); an edited guide is never overwritten."""
	path = os.path.join(frappe.get_app_path("smart_power", "sp_core"), *SEED_FILE)
	# the app's own seed file, never a path from a request
	with open(path, encoding="utf-8") as f:  # nosemgrep
		seeds = json.load(f)["guides"]
	added = 0
	for seed in seeds:
		if frappe.db.exists(GUIDE, seed["profile"]) or seed["profile"] not in _profiles():
			continue
		frappe.get_doc({"doctype": GUIDE, "is_active": 1, **seed}).insert(ignore_permissions=True)
		added += 1
	return added


def guides_for(user: str) -> list[str]:
	"""The active guides whose profile's roles the user holds, every one of them; all for the admin."""
	names = frappe.get_all(GUIDE, {"is_active": 1}, pluck="name", order_by="title asc")
	if is_admin(user):
		return names
	roles = set(frappe.get_roles(user))
	return [n for n in names if profile_roles(n) and profile_roles(n) <= roles]


def query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if is_admin(user):
		return ""
	names = guides_for(user)
	if not names:
		return "1 = 0"
	return "`tabSP User Guide`.`name` in ({})".format(", ".join(frappe.db.escape(n) for n in names))


def has_permission(doc, ptype=None, user=None) -> bool:
	user = user or frappe.session.user
	if is_admin(user):
		return True
	return ptype in (None, "read", "print") and doc.name in guides_for(user)


@frappe.whitelist()
def my_guides() -> list[dict]:
	"""What the Help page shows: the user's guides, their tasks, the top three first."""
	out = []
	for name in guides_for(frappe.session.user):
		doc = frappe.get_doc(GUIDE, name)
		tasks = sorted(doc.tasks, key=lambda t: (0 if t.is_top else 1, t.idx))
		out.append(
			{
				"name": doc.name,
				"title": doc.title,
				"home": doc.home,
				"menu": doc.menu,
				"screens": _lines(doc.screens),
				"dos": _lines(doc.dos),
				"donts": _lines(doc.donts),
				"tasks": [
					{
						"task": t.task,
						"is_top": cint(t.is_top),
						"steps": _lines(t.steps),
						"screen": t.screen,
						"video_url": t.video_url,
					}
					for t in tasks
				],
			}
		)
	return out


def _lines(text: str | None) -> list[str]:
	return [line.strip() for line in (text or "").split("\n") if line.strip()]


# --- the training session -------------------------------------------------------------------------


def validate_session(doc) -> None:
	top = [t.task for t in frappe.get_doc(GUIDE, doc.guide).tasks if t.is_top][:TOP_TASKS]
	doc.top_task_1, doc.top_task_2, doc.top_task_3 = (top + [None] * TOP_TASKS)[:TOP_TASKS]
	before = doc.get_doc_before_save()
	old = {r.name: r for r in (before.attendees if before else [])}
	seen = set()
	for row in doc.attendees:
		if row.user in seen:
			frappe.throw(_("{0} is listed twice.").format(row.user))
		seen.add(row.user)
		done = cint(row.attended) and cint(row.task_1) and cint(row.task_2) and cint(row.task_3)
		row.completed = 1 if done else 0
		was = cint(old[row.name].completed) if row.name in old else 0
		if row.completed and not was:
			row.observed_by, row.observed_on = frappe.session.user, now_datetime()
		elif not row.completed:
			row.observed_by, row.observed_on = None, None
	doc.completed_count = sum(1 for r in doc.attendees if r.completed)


def training_report(filters: dict) -> tuple[list, list]:
	"""Every active user with a Smart Power role: their guides, and their best training result."""
	if not is_admin():
		frappe.throw(_("Only the admin reads the training status."), frappe.PermissionError)
	from smart_power.sp_core.cutover import _users

	rows = frappe.db.sql(
		"""select a.user, a.attended, a.completed, s.name as session, s.session_date, s.guide
		from `tabSP Training Attendee` a join `tabSP Training Session` s on s.name = a.parent
		where a.parenttype = 'SP Training Session' and s.docstatus < 2
		order by a.completed desc, s.session_date desc""",
		as_dict=True,
	)
	best = {}
	for r in rows:
		best.setdefault(r.user, r)
	titles = dict(frappe.get_all(GUIDE, fields=["name", "title"], as_list=True))
	data = []
	for user in _users():
		result = best.get(user) or {}
		completed = cint(result.get("completed"))
		if cint(filters.get("only_open")) and completed:
			continue
		data.append(
			{
				"user": user,
				"full_name": frappe.db.get_value("User", user, "full_name"),
				"guides": ", ".join(titles.get(g, g) for g in guides_for(user) if not is_admin(user))
				or (_("All (admin)") if is_admin(user) else _("None")),
				"attended": cint(result.get("attended")),
				"completed": completed,
				"session": result.get("session"),
				"session_date": result.get("session_date"),
			}
		)
	columns = [
		{"fieldname": "user", "label": _("User"), "fieldtype": "Link", "options": "User", "width": WIDE},
		{"fieldname": "full_name", "label": _("Full Name"), "fieldtype": "Data", "width": NAME_WIDTH},
		{"fieldname": "guides", "label": _("Guide"), "fieldtype": "Data", "width": WIDE},
		{"fieldname": "attended", "label": _("Attended"), "fieldtype": "Check", "width": CHECK_WIDTH},
		{"fieldname": "completed", "label": _("Completed"), "fieldtype": "Check", "width": CHECK_WIDTH},
		{
			"fieldname": "session",
			"label": _("Session"),
			"fieldtype": "Link",
			"options": SESSION,
			"width": LINK_WIDTH,
		},
		{"fieldname": "session_date", "label": _("Session Date"), "fieldtype": "Date", "width": DATE_WIDTH},
	]
	return columns, data
