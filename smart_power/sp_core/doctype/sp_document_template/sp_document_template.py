# Copyright (c) 2026, Smart Power and contributors
# For license information, please see license.txt

"""A document template (SP-134, X8): the text blocks of one printed document.

Each version is its own record (<document>-v<n>). One version per document is published, and
a published version never changes: "New Version" copies it into a draft. New prints use the
published version; a document already sent keeps its saved PDF (SP-61).
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Max
from frappe.utils import cint, now_datetime

from smart_power.sp_core import documents

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
STATUS_FIELDS = ("is_published", "published_on", "notes")


class SPDocumentTemplate(Document):
	def autoname(self):
		self.version = next_version(self.document)
		self.name = f"{self.document}-v{self.version}"

	def onload(self):
		self.set_onload("placeholders", documents.placeholders_of(self.document))

	def validate(self):
		before = None if self.is_new() else self.get_doc_before_save()
		if before and before.is_published and content(before) != content(self):
			frappe.throw(
				_("Version {0} is published and cannot change. Make a new version.").format(
					frappe.bold(self.name)
				),
				title=_("Published template"),
			)
		keys = set()
		for row in self.blocks:
			where = _("Block {0}").format(frappe.bold(row.block_key or row.idx))
			row.block_key = (row.block_key or "").strip()
			if not KEY_PATTERN.match(row.block_key):
				frappe.throw(
					_("{0}: the key must start with a letter and use only a-z, 0-9 and _.").format(where)
				)
			if row.block_key in keys:
				frappe.throw(_("{0}: the key is used twice.").format(where))
			keys.add(row.block_key)
			documents.check_placeholders(self.document, row.title, where)
			documents.check_placeholders(self.document, row.body, where)

	@frappe.whitelist()
	def publish(self):
		"""Publish this version; the document's other published version stops."""
		self.check_permission("write")
		self.publish_now()

	def publish_now(self):
		"""Publish without a permission check (the app's own seeding)."""
		if not self.blocks:
			frappe.throw(_("A template needs at least one block before it is published."))
		for name in frappe.get_all(
			"SP Document Template",
			{"document": self.document, "is_published": 1, "name": ("!=", self.name)},
			pluck="name",
		):
			frappe.db.set_value("SP Document Template", name, "is_published", 0)
		self.db_set({"is_published": 1, "published_on": now_datetime()})
		self.add_comment("Info", _("Published"))

	@frappe.whitelist()
	def unpublish(self):
		self.check_permission("write")
		self.db_set("is_published", 0)
		self.add_comment("Info", _("Unpublished"))

	@frappe.whitelist()
	def new_version(self) -> str:
		frappe.has_permission("SP Document Template", "create", throw=True)
		copy = frappe.copy_doc(self, ignore_no_copy=False)  # a new version starts as an unpublished draft
		copy.previous_version = self.name
		copy.insert()
		return copy.name

	@frappe.whitelist()
	def preview(self, reference: str | None = None) -> list[str]:
		"""The blocks filled for a document of this kind (e.g. a quote), to check the text."""
		self.check_permission("read")
		doc = None
		doctype = DOCTYPES.get(self.document)
		if reference and doctype:
			doc = frappe.get_doc(doctype, reference)
			doc.check_permission("read")
		return [
			str(documents._render(frappe._dict(block_key=b.block_key, title=b.title, body=b.body), doc))
			for b in self.blocks
		]


# the ERPNext DocType a preview can be filled from (the others come with their stories)
DOCTYPES = {
	"Quotation": "Quotation",
	"Contract": "Sales Order",
	"Invoice": "Sales Invoice",
	"Purchase Order": "Purchase Order",
	"Delivery Note": "Delivery Note",
	"Warranty Certificate": "SP Station",
}


def next_version(document: str) -> int:
	template = frappe.qb.DocType("SP Document Template")
	(last,) = (
		frappe.qb.from_(template).select(Max(template.version)).where(template.document == document)
	).run()[0]
	return cint(last) + 1


def content(doc) -> str:
	data = doc.as_dict(no_default_fields=True)
	for field in (*STATUS_FIELDS, "version", "previous_version"):
		data.pop(field, None)
	data["blocks"] = [
		{k: v for k, v in row.items() if k not in ("name", "idx", "parent", "parentfield", "parenttype")}
		for row in data.get("blocks") or []
	]
	return json.dumps(data, sort_keys=True, default=str)
