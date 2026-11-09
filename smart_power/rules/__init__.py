"""Business rules engine (SP-128, tech plan section 6).

A rule is a Python function registered under a key with the `@rule` decorator. Its level
(Off, Warn or Block), its limits and its scope are data in an `SP Rule Setting` row that
the admin edits. One entry point, `run(doc, event)`, evaluates every active rule for the
document and enforces the outcome:

- Off: the rule is not evaluated, nothing is shown or logged.
- Warn: an orange banner, an `SP Rule Hit` and an open `SP Review Item`. When the rule's
  setting asks for a reason, saving stops until a reason is given.
- Block: saving is refused with a red message and the hit is logged. A user holding the
  override role (SP Admin) can pass with a reason; that writes an `SP Rule Override Log`.

Reasons reach the engine through `doc.flags.sp_rule_reasons` (server code) or the
`__sp_rule_reasons` key the desk client sends with the document: a dict {rule_key: reason}.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import frappe
from frappe import _

OFF, WARN, BLOCK = "Off", "Warn", "Block"
LEVELS = (OFF, WARN, BLOCK)

OUTCOME_WARNED, OUTCOME_BLOCKED, OUTCOME_OVERRIDDEN = "Warned", "Blocked", "Overridden"

RULE_SETTING = "SP Rule Setting"
OVERRIDE_ROLE = "SP Admin"


class RuleBlocked(frappe.ValidationError):
	"""A rule at Block refused the save."""


class RuleReasonRequired(frappe.ValidationError):
	"""A rule at Warn needs a reason before the save can go on."""


@dataclass(frozen=True)
class RuleSpec:
	key: str
	func: Callable[[Any, RuleContext], Finding | None]
	doctypes: tuple[str, ...]
	events: tuple[str, ...]
	category: str
	default_level: str
	never_block: bool
	warn_needs_reason: bool
	review_category: str
	title: str
	description: str


@dataclass
class Finding:
	"""What a rule returns when it fires. Return None when the document passes."""

	message: str
	suggestion: str | None = None
	amount: float | None = None
	highlight: bool = False
	data: dict = field(default_factory=dict)


@dataclass
class RuleContext:
	key: str
	level: str
	limits: dict
	event: str

	@property
	def settings(self):
		from smart_power.sp_core.services.settings import get_settings

		return get_settings()


@dataclass
class Hit:
	spec: RuleSpec
	level: str
	finding: Finding
	setting_name: str


_REGISTRY: dict[str, RuleSpec] = {}
_loaded = False


def rule(
	key: str,
	*,
	doctypes: Iterable[str],
	events: Iterable[str] = ("validate",),
	category: str = "Commercial",
	default_level: str = WARN,
	never_block: bool = False,
	warn_needs_reason: bool = False,
	review_category: str = "Rule Warning",
	title: str | None = None,
	description: str = "",
):
	"""Register a rule function under `key`.

	The function receives (doc, ctx: RuleContext) and returns a Finding when the rule fires.
	"""
	if default_level not in LEVELS:
		raise ValueError(f"Unknown level {default_level!r} for rule {key}")

	def decorator(func):
		_REGISTRY[key] = RuleSpec(
			key=key,
			func=func,
			doctypes=tuple(doctypes),
			events=tuple(events),
			category=category,
			default_level=WARN if never_block and default_level == BLOCK else default_level,
			never_block=never_block,
			warn_needs_reason=warn_needs_reason,
			review_category=review_category,
			title=title or key.replace("_", " ").capitalize(),
			description=description,
		)
		return func

	return decorator


def unregister(key: str) -> None:
	"""Remove a rule from the registry (used by tests)."""
	_REGISTRY.pop(key, None)


def load_rule_modules() -> None:
	"""Import every module listed in the `sp_rule_modules` hook so their rules register."""
	global _loaded
	if _loaded:
		return
	for path in frappe.get_hooks("sp_rule_modules"):
		frappe.get_module(path)
	_loaded = True


def registry() -> dict[str, RuleSpec]:
	load_rule_modules()
	return _REGISTRY


def rules_for(doctype: str, event: str) -> list[RuleSpec]:
	return [s for s in registry().values() if doctype in s.doctypes and event in s.events]


# --- settings -------------------------------------------------------------------------------


def get_rule_setting(key: str) -> frappe._dict | None:
	"""The admin's row for a rule, cached per request. None when the row does not exist yet."""
	cache = getattr(frappe.local, "sp_rule_settings", None)
	if cache is None:
		cache = frappe.local.sp_rule_settings = {}
	if key not in cache:
		row = frappe.db.get_value(
			RULE_SETTING,
			key,
			["name", "level", "limits", "scope_doctype", "scope_offer_type", "warn_needs_reason"],
			as_dict=True,
		)
		if row:
			row.limits = _parse_limits(row.limits)
		cache[key] = row
	return cache[key]


def clear_cache(doc=None, method=None) -> None:
	frappe.local.sp_rule_settings = {}


def _parse_limits(raw) -> dict:
	if not raw:
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		value = json.loads(raw)
	except ValueError:
		frappe.log_error(title="SP rule limits are not valid JSON", message=str(raw))
		return {}
	return value if isinstance(value, dict) else {}


def effective_level(spec: RuleSpec, setting) -> str:
	level = (setting.level if setting else None) or spec.default_level
	if spec.never_block and level == BLOCK:
		return WARN
	return level


def _in_scope(setting, doc) -> bool:
	if not setting:
		return True
	if setting.scope_doctype and setting.scope_doctype != doc.doctype:
		return False
	if setting.scope_offer_type:
		offer_type = doc.get("sp_offer_type")
		if offer_type and offer_type != setting.scope_offer_type:
			return False
	return True


# --- evaluate and enforce ---------------------------------------------------------------------


def evaluate(doc, event: str) -> list[Hit]:
	"""Run the active rules for doc and event and return the hits, without enforcing them."""
	hits: list[Hit] = []
	for spec in rules_for(doc.doctype, event):
		setting = get_rule_setting(spec.key)
		level = effective_level(spec, setting)
		if level == OFF or not _in_scope(setting, doc):
			continue
		ctx = RuleContext(key=spec.key, level=level, limits=(setting.limits if setting else {}), event=event)
		finding = spec.func(doc, ctx)
		if finding:
			hits.append(
				Hit(spec=spec, level=level, finding=finding, setting_name=setting.name if setting else "")
			)
	return hits


def run(doc, event: str = "validate") -> list[Hit]:
	"""Evaluate and enforce the rules for doc. Raises RuleBlocked or RuleReasonRequired."""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_import:
		return []
	hits = evaluate(doc, event)
	if hits:
		enforce(doc, hits)
	return hits


def on_doc_event(doc, method=None) -> None:
	"""doc_events hook target: maps the Frappe method name to the rule event."""
	if not _has_rules_for(doc.doctype, method):
		return
	run(doc, method)


def _has_rules_for(doctype: str, event: str) -> bool:
	return any(doctype in s.doctypes and event in s.events for s in registry().values())


def get_reasons(doc) -> dict:
	reasons = doc.flags.get("sp_rule_reasons") or doc.get("__sp_rule_reasons") or {}
	if isinstance(reasons, str):
		reasons = _parse_limits(reasons)
	return {k: (v or "").strip() for k, v in reasons.items() if (v or "").strip()}


def can_override(user: str | None = None) -> bool:
	user = user or frappe.session.user
	return user == "Administrator" or OVERRIDE_ROLE in frappe.get_roles(user)


def enforce(doc, hits: list[Hit]) -> None:
	reasons = get_reasons(doc)
	blocked = [h for h in hits if h.level == BLOCK]
	warned = [h for h in hits if h.level == WARN]

	# Blocks first: the save stops unless the admin overrides each one with a reason.
	not_overridden = [h for h in blocked if not (can_override() and reasons.get(h.spec.key))]
	if not_overridden:
		_log_blocks_after_rollback(doc, not_overridden)
		_response()["sp_rule_hits"] = [_as_payload(h) for h in hits]
		frappe.throw(
			_html_list(not_overridden),
			exc=RuleBlocked,
			title=_("Blocked by a business rule"),
		)

	missing_reason = [h for h in warned if _needs_reason(h) and not reasons.get(h.spec.key)]
	if missing_reason:
		_response()["sp_rule_hits"] = [_as_payload(h) for h in hits]
		frappe.throw(
			_html_list(missing_reason) + "<br>" + _("Give a reason for each warning to continue."),
			exc=RuleReasonRequired,
			title=_("A reason is needed"),
		)

	for h in blocked:
		_record(doc, h, OUTCOME_OVERRIDDEN, reasons.get(h.spec.key))
	for h in warned:
		_record(doc, h, OUTCOME_WARNED, reasons.get(h.spec.key))
		frappe.msgprint(h.finding.message, title=_("Warning"), indicator="orange", alert=True)


def _response() -> dict:
	response = getattr(frappe.local, "response", None)
	if response is None:
		response = frappe.local.response = frappe._dict()
	return response


def _needs_reason(hit: Hit) -> bool:
	setting = get_rule_setting(hit.spec.key)
	if setting is not None and setting.warn_needs_reason is not None:
		return bool(setting.warn_needs_reason)
	return hit.spec.warn_needs_reason


def _html_list(hits: list[Hit]) -> str:
	items = []
	for h in hits:
		text = frappe.utils.escape_html(h.finding.message)
		if h.finding.suggestion:
			text += " — " + frappe.utils.escape_html(h.finding.suggestion)
		items.append(f"<li><b>{frappe.utils.escape_html(_(h.spec.title))}</b>: {text}</li>")
	return "<ul>" + "".join(items) + "</ul>"


def _as_payload(h: Hit) -> dict:
	return {
		"rule": h.spec.key,
		"title": _(h.spec.title),
		"level": h.level,
		"message": h.finding.message,
		"suggestion": h.finding.suggestion,
		"needs_reason": h.level == BLOCK or _needs_reason(h),
	}


# --- logging ----------------------------------------------------------------------------------


def _record(doc, hit: Hit, outcome: str, reason: str | None) -> None:
	from smart_power.sp_core.services.review import open_review_item

	_insert_hit(doc, hit, outcome, reason)
	if outcome == OUTCOME_OVERRIDDEN:
		frappe.get_doc(
			{
				"doctype": "SP Rule Override Log",
				"rule": hit.setting_name or None,
				"rule_key": hit.spec.key,
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"user": frappe.session.user,
				"reason": reason,
				"message": hit.finding.message,
			}
		).insert(ignore_permissions=True, ignore_links=True)
	open_review_item(
		category="Override" if outcome == OUTCOME_OVERRIDDEN else hit.spec.review_category,
		reference_doctype=doc.doctype,
		reference_name=doc.name,
		summary=hit.finding.message,
		amount=hit.finding.amount,
		highlight=hit.finding.highlight,
		rule=hit.setting_name or None,
		reason=reason,
	)


def _insert_hit(doc, hit: Hit, outcome: str, reason: str | None) -> None:
	today = frappe.utils.today()
	exists = frappe.db.exists(
		"SP Rule Hit",
		{
			"rule_key": hit.spec.key,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"outcome": outcome,
			"message": hit.finding.message,
			"hit_at": (">=", today),
		},
	)
	if exists:
		return
	frappe.get_doc(
		{
			"doctype": "SP Rule Hit",
			"rule": hit.setting_name or None,
			"rule_key": hit.spec.key,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"level": hit.level,
			"outcome": outcome,
			"message": hit.finding.message,
			"reason": reason,
			"user": frappe.session.user,
			"hit_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True, ignore_links=True)


def _log_blocks_after_rollback(doc, hits: list[Hit]) -> None:
	"""A block rolls the request back, so its hits are written after the rollback."""
	frappe.db.after_rollback.add(functools.partial(write_blocked_hits, doc.doctype, doc.name, hits))


def write_blocked_hits(doctype: str, name: str, hits: list[Hit], commit: bool = True) -> None:
	try:
		ref = frappe._dict(doctype=doctype, name=name)
		for h in hits:
			_insert_hit(ref, h, OUTCOME_BLOCKED, None)
		if commit:
			frappe.db.commit()
	except Exception:
		frappe.log_error(title="SP rule hit could not be logged")


# --- setup ------------------------------------------------------------------------------------


def sync_rule_settings() -> None:
	"""Create an SP Rule Setting row for every registered rule that has none.

	Runs after every migrate. Existing rows are the admin's: their level, limits and scope are
	never touched. Only the developer-owned description fields are refreshed.
	"""
	from smart_power.sp_core.setup.seed import seed_rule_values

	seeds = seed_rule_values()
	for spec in registry().values():
		dev_fields = {
			"title": spec.title,
			"category": spec.category,
			"description": spec.description,
			"never_block": int(spec.never_block),
			"applies_to": ", ".join(spec.doctypes),
			"events": ", ".join(spec.events),
		}
		if frappe.db.exists(RULE_SETTING, spec.key):
			frappe.db.set_value(RULE_SETTING, spec.key, dev_fields, update_modified=False)
			continue
		seed = seeds.get(spec.key, {})
		doc = frappe.get_doc(
			{
				"doctype": RULE_SETTING,
				"rule_key": spec.key,
				"level": effective_level(spec, frappe._dict(level=seed.get("level"))),
				"warn_needs_reason": int(seed.get("warn_needs_reason", spec.warn_needs_reason)),
				"limits": json.dumps(seed.get("limits") or {}, indent=1),
				**dev_fields,
			}
		)
		doc.insert(ignore_permissions=True)
	clear_cache()
