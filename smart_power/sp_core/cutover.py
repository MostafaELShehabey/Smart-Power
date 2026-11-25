"""Go-live cutover and hypercare (E17, SP-163): the runbook as a checklist, ticked by its owners.

A new SP Cutover is seeded with the runbook (the dates of the scope note of 6-11-2026, counted from
the go-live date), the rollback plan per module, and nothing else. On it:

- **Steps:** each has a planned date, an owner role and the person the admin names. Only that
  person, or the admin, ticks it, and the tick keeps when and by whom. Naming a person gives them
  a task; the tick closes it. Some steps are checked before they are ticked:
      smoke             every user's smoke test passed on the last run
      january_close     the go-live month is closed (SP Month Close, SP-126)
      hypercare_review  January is closed and the last hypercare day has no open Highest defect
- **Smoke tests** (run_smoke): for every active user, as that user: the account (enabled, not
  locked, with an SP role), the home (the cards, or the field pages for a light-entry user), and
  the main action of each of their roles (MAIN_ACTIONS). Each user's first login since go-live
  shows beside it.
- **Rollback:** per module, the criterion and the person who decides; a decision keeps when and by
  whom it was recorded.
- **Hypercare:** one row per day for four weeks (start_hypercare): the check-in, the backup
  verified (who and when), the open Highest and High defects.

WhatsApp stays allowed; from day one the system is the official record (scope note 6-11-2026).
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, now_datetime

from smart_power.sp_core.inbox import create_task
from smart_power.sp_core.web import LIGHT_ENTRY

CUTOVER, TASK = "SP Cutover", "SP Task"
TASK_TYPE = "Cutover Step"
ADMIN_ROLES = ("SP Admin", "System Manager")
ADMIN, DELIVERY, ACCOUNTANT, STORE = "SP Admin", "System Manager", "SP Accountant", "SP Main Store Keeper"
SMOKE, JANUARY_CLOSE, HYPERCARE_REVIEW = "smoke", "january_close", "hypercare_review"
PASS, FAIL = "Pass", "Fail"
PLANNED, IN_PROGRESS, DONE = "Planned", "In progress", "Done"
HYPERCARE_DAYS = 28  # sp-allow-number: four weeks
FULL_PERCENT = 100  # sp-allow-number: a percentage

# days from go-live: the runbook's dates (scope note of 6-11-2026)
FREEZE, REHEARSAL, SIGN_OFF, COUNT, EVE, GO_LIVE = -12, -8, -7, -3, -1, 0  # sp-allow-number: the runbook
DRY_RUN, READ_ONLY, CLOSE = 14, 30, 31  # sp-allow-number: the runbook
# (days from go-live, step, owner role, key)
RUNBOOK = (
	(FREEZE, "تجميد تعديل البيانات الأساسية في الإكسل، وتصدير نهائي من المالك", ADMIN, None),
	(REHEARSAL, "بروفة كاملة على نسخة الاختبار: نقل البيانات الأساسية والأرصدة الافتتاحية", DELIVERY, None),
	(SIGN_OFF, "اعتماد اختبار القبول النهائي، وتجهيز موقع التشغيل والمستخدمين", DELIVERY, None),
	(COUNT, "جرد المخزون بأكواد الأصناف الجديدة (29-30 ديسمبر)", STORE, None),
	(EVE, "إقفال أرصدة الإكسل في 31-12", ACCOUNTANT, None),
	(EVE, "نقل البيانات الأساسية على موقع التشغيل ومطابقة الأعداد مع الملفات", DELIVERY, None),
	(GO_LIVE, "تحميل الأرصدة الافتتاحية (A15)", ADMIN, None),
	(GO_LIVE, "مطابقة ميزان المراجعة مع قائمة 31-12 وتوقيع المالك", ADMIN, None),
	(GO_LIVE, "مراجعة المخزون والأمانات", STORE, None),
	(GO_LIVE, "اختبارات التشغيل لكل مستخدم: الدخول والصفحة الرئيسية وإجراء واحد", DELIVERY, SMOKE),
	(
		GO_LIVE,
		"الطلبات والموافقات والتنبيهات من النظام من أول يوم (واتساب مسموح، لكنه ليس السجل الرسمي)",
		ADMIN,
		None,
	),
	(GO_LIVE, "التحقق من وصول الإشعارات", DELIVERY, None),
	(DRY_RUN, "تجربة إقفال الشهر (الأسبوع الثاني)", ACCOUNTANT, None),
	(READ_ONLY, "الإكسل للقراءة فقط طوال يناير", ADMIN, None),
	(CLOSE, "إقفال يناير في النظام (A14)", ADMIN, JANUARY_CLOSE),
	(CLOSE, "مراجعة نهاية الدعم المكثف: يناير مقفل ولا أخطاء عاجلة مفتوحة", ADMIN, HYPERCARE_REVIEW),
)
ROLLBACK_CRITERION = "عطل يوقف العمل في هذا الجزء خلال أول 48 ساعة بلا حل بديل"
ROLLBACK_MODULES = (
	"المبيعات والمتابعة",
	"عروض الأسعار",
	"المحطات والعقود",
	"المشتريات والاستلام",
	"المخزون والأمانات",
	"المالية والخزينة",
	"الونش والعربية الجامبو",
	"المعرض",
)

# the main action of each role: the doctype it works on, and how
MAIN_ACTIONS = {
	"SP Admin": (CUTOVER, "write"),
	"SP Accountant": ("Journal Entry", "create"),
	"SP Commission Manager": ("SP Team Commission", "read"),
	"SP Collection Officer": ("SP Customer Payment", "create"),
	"SP Bank Financing": ("SP Customer Advance", "create"),
	"SP Lead Intake": ("SP Case", "create"),
	"SP Customer Followup": ("SP Case", "write"),
	"SP Followup All": ("SP Case", "read"),
	"SP Site Survey": ("SP Site Survey", "write"),
	"SP Marketing Agent": ("Lead", "create"),
	"SP System Designer": ("Quotation", "read"),
	"SP Quote Creator": ("Quotation", "create"),
	"SP Catalog Manager": ("Item", "create"),
	"SP Pricing Manager": ("Item Price", "write"),
	"SP Contract Manager": ("Sales Order", "create"),
	"SP Project Manager": ("SP Station", "write"),
	"SP Purchase Officer": ("Purchase Order", "create"),
	"SP Receipt Confirmer": ("Purchase Receipt", "read"),
	"SP Main Store Keeper": ("Stock Entry", "create"),
	"SP Showroom Store Keeper": ("Stock Entry", "create"),
	"SP Site Receiver": ("Stock Entry", "read"),
	"SP Showroom Sales": ("Sales Invoice", "create"),
	"SP Showroom Cashier": ("SP Cash Box Day", "create"),
	"SP Installation Manager": ("SP Site Daily Log", "create"),
	"SP Installation Technician": ("SP Site Daily Log", "create"),
	"SP Commissioning Programmer": ("SP Commissioning", "create"),
	"SP Warranty Service": ("SP Warranty", "read"),
	"SP Winch Manager": ("SP Vehicle Booking", "create"),
	"SP Winch Reviewer": ("SP Field Review", "read"),
	"SP Winch Operator": ("SP Field Entry", "create"),
	"SP Driver": ("SP Field Entry", "create"),
	"SP Custody Holder": ("SP Custody Settlement", "create"),
}


def is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles(user)))


def _check_admin() -> None:
	if not is_admin():
		frappe.throw(_("Only the admin runs the cutover."), frappe.PermissionError)


# --- the record -------------------------------------------------------------------------------------


def before_insert(doc) -> None:
	"""A new cutover starts from the runbook and the rollback plan."""
	day = getdate(doc.go_live_date)
	if not doc.steps:
		for offset, step, role, key in RUNBOOK:
			doc.append(
				"steps",
				{"planned_on": add_days(day, offset), "step": step, "owner_role": role, "step_key": key},
			)
	if not doc.rollback:
		for module in ROLLBACK_MODULES:
			doc.append("rollback", {"module": module, "criterion": ROLLBACK_CRITERION})


def validate(doc) -> None:
	"""Ticks come only through tick(), decisions and backups keep who and when."""
	before = doc.get_doc_before_save()
	old_steps = {r.name: r for r in (before.steps if before else [])}
	for row in doc.steps:
		old = old_steps.get(row.name)
		if not doc.flags.sp_tick:
			row.done, row.done_at, row.done_by = (
				(old.done, old.done_at, old.done_by) if old else (0, None, None)
			)
		if row.owner_user and not frappe.db.get_value("User", row.owner_user, "enabled"):
			frappe.throw(_("Row {0}: {1} is not an active user.").format(row.idx, row.owner_user))
	old_rollback = {r.name: r for r in (before.rollback if before else [])}
	for row in doc.rollback:
		old = old_rollback.get(row.name)
		if (row.decision or "") != ((old.decision or "") if old else ""):
			row.decided_at, row.decided_by = (
				(now_datetime(), frappe.session.user) if row.decision else (None, None)
			)
	old_days = {r.name: r for r in (before.hypercare if before else [])}
	for row in doc.hypercare:
		old = old_days.get(row.name)
		if cint(row.backup_verified) != cint(old.backup_verified if old else 0):
			row.backup_verified_at, row.backup_verified_by = (
				(now_datetime(), frappe.session.user) if row.backup_verified else (None, None)
			)
	done = sum(1 for r in doc.steps if r.done)
	doc.progress = round(done * FULL_PERCENT / len(doc.steps)) if doc.steps else 0
	doc.status = DONE if doc.steps and done == len(doc.steps) else (IN_PROGRESS if done else PLANNED)


def on_update(doc) -> None:
	"""A person named on a step gets a task for it."""
	before = doc.get_doc_before_save()
	old = {r.name: r.owner_user for r in (before.steps if before else [])}
	for row in doc.steps:
		if row.owner_user and not row.done and old.get(row.name) != row.owner_user:
			create_task(
				TASK_TYPE,
				CUTOVER,
				doc.name,
				[row.owner_user],
				_subject(row),
				due_at=get_datetime(row.planned_on) if row.planned_on else None,
				distinct_subject=True,
			)


def _subject(row) -> str:
	return _("Cutover: {0} ({1})").format(
		row.step, frappe.format(row.planned_on, "Date") if row.planned_on else ""
	)


def _row(doc, row_name: str):
	row = next((r for r in doc.steps if r.name == row_name), None)
	if not row:
		frappe.throw(_("The step is not on {0}.").format(doc.name))
	return row


# --- ticking ----------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def tick(name: str, row: str, note: str | None = None) -> dict:
	"""The step's owner (or the admin) ticks it; when and by whom are kept."""
	doc = frappe.get_doc(CUTOVER, name)
	step = _row(doc, row)
	user = frappe.session.user
	if step.owner_user != user and not is_admin(user):
		frappe.throw(
			_("Only {0} or the admin ticks this step.").format(step.owner_user or _("its owner")),
			frappe.PermissionError,
		)
	if step.done:
		frappe.throw(_("The step is already ticked."))
	_check_step(doc, step)
	step.done, step.done_at, step.done_by = 1, now_datetime(), user
	if note:
		step.note = note
	doc.flags.sp_tick = True
	doc.flags.ignore_permissions = True
	doc.save()
	_close_task(doc, step)
	return {"done_at": step.done_at, "done_by": user, "progress": doc.progress, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def untick(name: str, row: str) -> dict:
	_check_admin()
	doc = frappe.get_doc(CUTOVER, name)
	step = _row(doc, row)
	step.done, step.done_at, step.done_by = 0, None, None
	doc.flags.sp_tick = True
	doc.save()
	return {"progress": doc.progress, "status": doc.status}


def _check_step(doc, step) -> None:
	if step.step_key == SMOKE:
		if not doc.smoke_tests:
			frappe.throw(_("Run the smoke tests first."))
		failed = [r.user for r in doc.smoke_tests if r.result != PASS]
		if failed:
			frappe.throw(_("The smoke tests failed for: {0}.").format(", ".join(failed)))
	elif step.step_key == JANUARY_CLOSE and not _month_closed(doc):
		frappe.throw(_("The go-live month is not closed yet (Month Close)."))
	elif step.step_key == HYPERCARE_REVIEW:
		closed = any(r.step_key == JANUARY_CLOSE and r.done for r in doc.steps)
		last = sorted(doc.hypercare, key=lambda r: getdate(r.day))[-1] if doc.hypercare else None
		if not closed:
			frappe.throw(_("Tick the January close first."))
		if not last or cint(last.open_highest):
			frappe.throw(_("The last hypercare day must show no open Highest defect."))


def _month_closed(doc) -> bool:
	month = getdate(doc.go_live_date).replace(day=1)
	return bool(
		frappe.db.exists("SP Month Close", {"company": doc.company, "month": month, "status": "Closed"})
	)


def _close_task(doc, step) -> None:
	for task in frappe.get_all(
		TASK,
		{
			"reference_doctype": CUTOVER,
			"reference_name": doc.name,
			"task_type": TASK_TYPE,
			"subject": _subject(step),
			"status": "Open",
		},
		pluck="name",
	):
		frappe.db.set_value(
			TASK,
			task,
			{"status": "Done", "completed_by": frappe.session.user, "completed_on": now_datetime()},
		)


# --- smoke tests ------------------------------------------------------------------------------------


def _users() -> list[str]:
	sp_roles = set(MAIN_ACTIONS) | {r.role_name for r in _catalogue()}
	holders = frappe.get_all(
		"Has Role", {"parenttype": "User", "role": ("in", sorted(sp_roles))}, pluck="parent"
	)
	return sorted(
		u
		for u in set(holders)
		if u not in ("Administrator", "Guest") and frappe.db.get_value("User", u, "enabled")
	)


def _catalogue():
	from smart_power.sp_core.setup.role_catalogue import ROLES

	return ROLES


def smoke_user(user: str, go_live) -> dict:
	"""One user's smoke test, as that user."""
	info = frappe.db.get_value(
		"User", user, ["full_name", "enabled", "sp_login_locked", "sp_entry_mode", "last_login"], as_dict=True
	)
	roles = sorted(set(frappe.get_roles(user)) & (set(MAIN_ACTIONS) | {r.role_name for r in _catalogue()}))
	problems = []
	account_ok = bool(info.enabled and not info.sp_login_locked and roles)
	if not account_ok:
		problems.append(_("The account is disabled, locked or has no Smart Power role."))
	home_ok = action_ok = False
	current = frappe.session.user
	frappe.set_user(user)  # nosemgrep
	try:
		try:
			_home(info.sp_entry_mode)
			home_ok = True
		except Exception as e:
			problems.append(_("Home: {0}").format(str(e)))
			frappe.clear_messages()
		actions = [(role, *MAIN_ACTIONS[role]) for role in roles if role in MAIN_ACTIONS]
		missing = [
			f"{_(role)}: {_(ptype)} {_(doctype)}"
			for role, doctype, ptype in actions
			if not frappe.has_permission(doctype, ptype, user=user)
		]
		action_ok = bool(actions) and not missing
		if not actions:
			problems.append(_("None of the roles has a main action to check."))
		if missing:
			problems.append(_("Not allowed: {0}").format("; ".join(missing)))
	finally:
		frappe.set_user(current)  # nosemgrep
	first_login = (
		info.last_login if info.last_login and getdate(info.last_login) >= getdate(go_live) else None
	)
	return {
		"user": user,
		"full_name": info.full_name,
		"roles": ", ".join(roles),
		"account_ok": int(account_ok),
		"home_ok": int(home_ok),
		"action_ok": int(action_ok),
		"result": PASS if account_ok and home_ok and action_ok else FAIL,
		"message": " ".join(problems),
		"first_login": first_login,
		"checked_on": now_datetime(),
	}


def _home(entry_mode: str | None) -> None:
	if entry_mode == LIGHT_ENTRY:
		from smart_power.sp_winch.field_page import options

		options()
		return
	from smart_power.dashboards.cards import get_home

	get_home()


@frappe.whitelist(methods=["POST"])
def run_smoke(name: str) -> dict:
	"""Every active user's smoke test; the results replace the last run's."""
	_check_admin()
	doc = frappe.get_doc(CUTOVER, name)
	results = [smoke_user(user, doc.go_live_date) for user in _users()]
	doc.set("smoke_tests", results)
	passed = sum(1 for r in results if r["result"] == PASS)
	doc.smoke_run_on = now_datetime()
	doc.smoke_summary = _("{0} of {1} users passed").format(passed, len(results))
	doc.save()
	return {"passed": passed, "total": len(results), "summary": doc.smoke_summary}


# --- hypercare --------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def start_hypercare(name: str) -> int:
	"""Four weeks of daily rows from the go-live date (the days already there are kept)."""
	_check_admin()
	doc = frappe.get_doc(CUTOVER, name)
	have = {getdate(r.day) for r in doc.hypercare}
	start = getdate(doc.go_live_date)
	for i in range(HYPERCARE_DAYS):
		day = add_days(start, i)
		if getdate(day) not in have:
			doc.append("hypercare", {"day": day})
	doc.save()
	return len(doc.hypercare)
