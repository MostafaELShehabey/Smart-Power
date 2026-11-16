"""Work date vs entry time (SP-44, component 4).

Wherever back-dating is allowed, the editable `work_date` (when it happened) sits beside the
read-only `entry_time` (when it was entered, set once on insert). A DocType gets this by its
controller inheriting SPDatedDocument; a work date may be in the past, never in the future.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime, nowdate


class SPDatedDocument(Document):
	def before_validate(self):
		set_dates(self)


def set_dates(doc) -> None:
	if not doc.get("entry_time"):
		doc.entry_time = now_datetime()
	if not doc.get("work_date"):
		doc.work_date = nowdate()
	if getdate(doc.work_date) > getdate(nowdate()):
		frappe.throw(
			_("The date {0} is still to come: record what has already happened.").format(
				frappe.format(doc.work_date, "Date")
			),
			title=_("Date in the future"),
		)
