"""Safe formulas for calculation templates (SP-55).

A template line's quantity (and, for "Brand priority", its need) is a small Python expression
the admin writes, for example ``ceil(depth / pipe_m)`` or ``depth * 2 + rope_allowance``. It is
run through ``frappe.safe_eval`` with only these names:

- the template's inputs, by their key;
- earlier lines, by their line key, with ``.qty``, ``.cost``, ``.rate``, ``.amount``,
  ``.cost_amount`` and ``.item`` (the picked item's specs);
- ``item``: the specs of the item picked for this line (``item.hp``, ``item.watt`` …);
- ``settings``: Smart Power Settings values;
- the helpers below.

Every name is checked when the template is saved, so a typo is caught there (naming the line)
and not on a customer's quote.
"""

import ast
import math
import re

import frappe
from frappe import _


def mround(value, step):
	"""Round to the nearest multiple of step (Excel's MROUND)."""
	return round(value / step) * step if step else value


def nearest_divisible(value, divisor):
	"""The smallest multiple of divisor that is at least value, e.g. a depth the pipes cover."""
	return math.ceil(value / divisor) * divisor if divisor else value


HELPERS = {
	"ceil": math.ceil,
	"floor": math.floor,
	"mround": mround,
	"nearest_divisible": nearest_divisible,
	"min": min,
	"max": max,
	"abs": abs,
	"round": round,
	"int": int,
	"float": float,
}
ITEM, SETTINGS = "item", "settings"
LINE_FIELDS = ("qty", "cost", "rate", "amount", "cost_amount", "item")
RESERVED = frozenset(HELPERS) | {ITEM, SETTINGS}
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def check_key(key: str, where: str) -> str:
	"""A key formulas can use: lower-case letters, digits and _, not a helper's name."""
	key = (key or "").strip()
	if not KEY_PATTERN.match(key):
		frappe.throw(
			_("{0}: the key {1} must start with a letter and use only a-z, 0-9 and _.").format(
				where, frappe.bold(key)
			),
			title=_("Check the template"),
		)
	if key in RESERVED:
		frappe.throw(
			_("{0}: {1} is a reserved name.").format(where, frappe.bold(key)), title=_("Check the template")
		)
	return key


def names_in(formula: str, where: str) -> set[str]:
	"""The names a formula reads. A formula that is not a plain expression is refused."""
	try:
		tree = ast.parse((formula or "").strip(), mode="eval")
	except SyntaxError:
		frappe.throw(
			_("{0}: the formula {1} cannot be read.").format(where, frappe.bold(formula)),
			title=_("Check the template"),
		)
	names = set()
	for node in ast.walk(tree):
		if isinstance(node, ast.Lambda | ast.NamedExpr):
			frappe.throw(_("{0}: this kind of formula is not allowed.").format(where))
		if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
			frappe.throw(_("{0}: {1} cannot be read.").format(where, frappe.bold(node.attr)))
		if isinstance(node, ast.Name):
			names.add(node.id)
	return names


def check(formula: str, known: set[str], where: str) -> None:
	"""Refuse a formula that uses a name it cannot know, naming the line."""
	unknown = sorted(names_in(formula, where) - set(known) - RESERVED)
	if unknown:
		frappe.throw(
			_("{0}: unknown name {1} in the formula {2}.").format(
				where, frappe.bold(", ".join(unknown)), frappe.bold(formula)
			),
			title=_("Check the template"),
		)


def evaluate(formula: str, namespace: dict, where: str) -> float:
	"""Run a formula with the given names (and the helpers). Errors name the line."""
	try:
		value = frappe.safe_eval((formula or "").strip(), {**HELPERS, **namespace})
	except ZeroDivisionError:
		frappe.throw(_("{0}: the formula {1} divides by zero.").format(where, frappe.bold(formula)))
	except (NameError, AttributeError, TypeError, ValueError, SyntaxError) as e:
		frappe.throw(_("{0}: the formula {1} failed: {2}").format(where, frappe.bold(formula), str(e)))
	if isinstance(value, bool):
		return float(value)
	if not isinstance(value, int | float):
		frappe.throw(_("{0}: the formula {1} must give a number.").format(where, frappe.bold(formula)))
	return float(value)
