# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class SPTask(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		assigned_to: DF.Link
		completed_by: DF.Link | None
		completed_on: DF.Datetime | None
		description: DF.SmallText | None
		due_at: DF.Datetime | None
		image: DF.AttachImage | None
		priority: DF.Literal["Normal", "High"]
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		snoozed_until: DF.Datetime | None
		status: DF.Literal["Open", "Done", "Cancelled"]
		subject: DF.Data
		task_type: DF.Literal[
			"Quote Request",
			"Follow-up Call",
			"Discount Request",
			"Receipt to Confirm",
			"Payment to Confirm",
			"Transfer to Confirm",
			"Entry to Review",
			"Reopen Request",
			"Make Contract",
			"Site Survey",
			"Transfer to Issue",
			"Settlement to Approve",
			"Count Difference",
			"Password Reset",
			"Fix Rejected Sync",
			"Reassign Request",
			"Technical Review",
			"Agri Bank Advance",
			"Other",
		]
	# end: auto-generated types

	def validate(self):
		if self.status == "Done" and not self.completed_on:
			self.completed_by = frappe.session.user
			self.completed_on = now_datetime()

	def on_update(self):
		"""The assignee's inbox and the shell's count follow at once (SP-39)."""
		from smart_power.sp_core.inbox import publish

		publish(self.assigned_to)
		before = self.get_doc_before_save()
		if before and before.assigned_to != self.assigned_to:
			publish(before.assigned_to)


def _sees_all(user: str) -> bool:
	return user == "Administrator" or bool({"SP Admin", "System Manager"} & set(frappe.get_roles(user)))


def get_permission_query_conditions(user: str | None = None) -> str:
	"""A user sees the tasks assigned to them or created by them; the admin sees all."""
	user = user or frappe.session.user
	if _sees_all(user):
		return ""
	escaped = frappe.db.escape(user)
	return f"(`tabSP Task`.assigned_to = {escaped} or `tabSP Task`.owner = {escaped})"


def has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _sees_all(user):
		return True
	return user in (doc.assigned_to, doc.owner)
