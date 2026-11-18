"""Pump curves (SP-184): the manufacturer's curve on the pump item, and whether it covers a duty.

A pump covers a required flow and head when the flow is inside its curve's flow range and its
head at that flow, read on the straight line between the two nearest points, is at least the
required head. Nothing is read beyond the ends of the curve: a manufacturer's curve says nothing
about a flow it does not list.

The default pump pick (SP-168) and the pump selector (SP-65) both use covers().
"""

from itertools import pairwise

import frappe
from frappe import _
from frappe.utils import flt

POINT = "SP Pump Curve Point"
HEAD_DIGITS = 3  # sp-allow-number: a millimetre of head, so rounding never decides a pick


def _sorted(points) -> list[tuple[float, float]]:
	return sorted((flt(p.get("flow_m3h")), flt(p.get("head_m"))) for p in points)


def check_curve(doc) -> None:
	"""Item validate: no negative point, one head per flow, and the rows in flow order."""
	rows = doc.get("sp_curve_points") or []
	seen = set()
	for row in rows:
		flow, head = flt(row.flow_m3h), flt(row.head_m)
		if flow < 0 or head < 0:
			frappe.throw(
				_("Curve point {0}: flow and head cannot be negative.").format(row.idx),
				title=_("Check the curve"),
			)
		if flow in seen:
			frappe.throw(
				_("The curve has flow {0} twice.").format(frappe.bold(f"{flow:g}")),
				title=_("Check the curve"),
			)
		seen.add(flow)
	rows.sort(key=lambda row: flt(row.flow_m3h))
	for idx, row in enumerate(rows, start=1):
		row.idx = idx


def head_at(points, flow: float) -> float | None:
	"""The curve's head at a flow, or None when the flow is outside the curve."""
	curve, flow = _sorted(points), flt(flow)
	if not curve or flow < curve[0][0] or flow > curve[-1][0]:
		return None
	for (low_flow, low_head), (high_flow, high_head) in pairwise(curve):
		if low_flow <= flow <= high_flow:
			share = (flow - low_flow) / (high_flow - low_flow)
			return flt(low_head + share * (high_head - low_head), HEAD_DIGITS)
	return flt(curve[0][1], HEAD_DIGITS)  # a curve of one point, at exactly that flow


def covers(points, head: float, flow: float) -> bool:
	"""Whether the curve delivers the required head at the required flow."""
	available = head_at(points, flow)
	return available is not None and available >= flt(head, HEAD_DIGITS)


def curve_of(item_code: str) -> list:
	"""A pump's curve points."""
	return frappe.get_all(
		POINT,
		{"parent": item_code, "parenttype": "Item", "parentfield": "sp_curve_points"},
		["flow_m3h", "head_m"],
		order_by="flow_m3h asc",
	)
