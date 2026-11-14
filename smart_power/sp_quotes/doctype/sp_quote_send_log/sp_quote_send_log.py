# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

"""One send of a quote version (SP-61): who, when, how, which format and the PDF sent.
Append-only: a send is a fact; it is never edited or deleted."""

from frappe.model.document import Document

from smart_power.sp_core.services.audit import prevent_change, prevent_delete


class SPQuoteSendLog(Document):
	def validate(self):
		prevent_change(self)

	def on_trash(self):
		prevent_delete(self)
