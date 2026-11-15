"""A1 Confirmations centre (SP-115): one queue of every money item waiting for the admin, with its
receipt and the entry it will post (journey J3).

Sources plug in through the `sp_confirmation_sources` hook: {DocType: module}. A source module
gives pending_items(filters), preview(name), confirm(name) and reject(name, reason). Customer
payments (SP-114) are the first; transfers (SP-117), custody settlements (SP-122) and cash-box
day closes (E11) add themselves when they land.

    pending(filters)          the queue (filter by kind, receiving account, dates) and its totals
    preview(doctype, name)    the exact Dr / Cr lines, center and station
    confirm / reject          one item (reject needs a reason; the recorder is told and tasked)
    bulk_confirm(items)       after checking a statement: a background job, item by item, each
                              committed on its own; failures are reported, the rest stay done
"""

import frappe
from frappe import _
from frappe.utils import flt, get_fullname

ADMIN_ROLES = ("SP Admin", "System Manager")
BULK_KEY = "sp_bulk_confirm:{0}"
BULK_TTL = 3600  # sp-allow-number: seconds the bulk result is kept for the page


def _check_admin() -> None:
	if frappe.session.user != "Administrator" and not set(ADMIN_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Only the admin confirms money."), frappe.PermissionError)


def sources() -> dict:
	"""{DocType: module}; Frappe merges the apps' dict hooks into lists, the last app wins."""
	hooks = frappe.get_hooks("sp_confirmation_sources") or {}
	return {
		doctype: (modules[-1] if isinstance(modules, list) else modules) for doctype, modules in hooks.items()
	}


def _source(doctype: str):
	module = sources().get(doctype)
	if not module:
		frappe.throw(_("{0} is not confirmed here.").format(frappe.bold(doctype)))
	return frappe.get_module(module)


@frappe.whitelist()
def pending(filters: str | dict | None = None) -> dict:
	"""Every pending item, oldest first, with the count and amount waiting (the Finance home)."""
	_check_admin()
	filters = frappe.parse_json(filters) or {}
	items = []
	for doctype, module in sources().items():
		if filters.get("doctype") and filters["doctype"] != doctype:
			continue
		items += frappe.get_module(module).pending_items(filters)
	for item in items:
		item["recorder_name"] = get_fullname(item["recorder"]) if item.get("recorder") else ""
	items.sort(key=lambda i: (str(i.get("date") or ""), i["name"]))
	return {
		"items": items,
		"count": len(items),
		"amount": sum(flt(i["amount"]) for i in items),
		"kinds": [{"doctype": d, "label": _(d)} for d in sources()],
	}


@frappe.whitelist()
def summary() -> dict:
	"""Count and amount waiting, for the Finance home."""
	data = pending()
	return {"count": data["count"], "amount": data["amount"]}


@frappe.whitelist()
def preview(doctype: str, name: str) -> list[dict]:
	_check_admin()
	return _source(doctype).preview(name)


@frappe.whitelist(methods=["POST"])
def confirm(doctype: str, name: str) -> str:
	_check_admin()
	return _source(doctype).confirm(name)


@frappe.whitelist(methods=["POST"])
def reject(doctype: str, name: str, reason: str) -> str:
	_check_admin()
	return _source(doctype).reject(name, reason)


@frappe.whitelist(methods=["POST"])
def bulk_confirm(items: str | list) -> str:
	"""Confirm the selected items in the background; returns the job's key for its results."""
	_check_admin()
	items = frappe.parse_json(items) if isinstance(items, str) else items
	key = BULK_KEY.format(frappe.generate_hash(length=12))  # sp-allow-number: id length
	frappe.cache.set_value(key, {"done": False, "results": []}, expires_in_sec=BULK_TTL)
	frappe.enqueue(
		"smart_power.sp_finance.confirmations.run_bulk",
		queue="short",
		key=key,
		items=items,
		enqueue_after_commit=True,
		now=frappe.flags.in_test,
	)
	return key


def run_bulk(key: str, items: list) -> list[dict]:
	"""Each item on its own: confirmed and committed, or rolled back and reported. Frappe runs
	the job as the admin who started it, so each source still checks who confirms."""
	results = []
	for i, item in enumerate(items):
		doctype, name = item.get("doctype"), item.get("name")
		savepoint = f"sp_bulk_{i}"
		frappe.db.savepoint(savepoint)
		try:
			entry = _source(doctype).confirm(name)
			if not frappe.flags.in_test:
				frappe.db.commit()  # nosemgrep: one item's success stays when a later one fails
			results.append({"doctype": doctype, "name": name, "ok": True, "entry": entry})
		except Exception as e:
			frappe.db.rollback(save_point=savepoint)
			frappe.clear_messages()
			results.append({"doctype": doctype, "name": name, "ok": False, "error": str(e)})
		frappe.cache.set_value(key, {"done": False, "results": results}, expires_in_sec=BULK_TTL)
	frappe.cache.set_value(key, {"done": True, "results": results}, expires_in_sec=BULK_TTL)
	return results


@frappe.whitelist()
def bulk_result(key: str) -> dict:
	_check_admin()
	if not key.startswith(BULK_KEY.format("")):
		frappe.throw(_("Unknown bulk confirmation."))
	return frappe.cache.get_value(key) or {"done": True, "results": []}
