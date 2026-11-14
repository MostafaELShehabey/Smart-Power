"""Document templates (SP-134, X8): the admin's text on printed documents.

A print format asks for a block of the published template of its document:

    {{ sp_block("Quotation", "warranty", doc) }}      one block (title and text)
    {% for block in sp_blocks("Quotation", doc) %}…   every block, in order

The text holds {placeholders}, filled by a plain formatter, never by Jinja, so text the admin
types cannot run code. Each document has its own placeholders (PLACEHOLDERS); a misspelled one
is refused when the template is saved, listing the valid ones.
"""

import re

import frappe
from frappe import _
from frappe.utils import cstr, flt
from markupsafe import Markup, escape

from smart_power.sp_core.printing import ar_date, ar_words, money

TEMPLATE = "SP Document Template"
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _company_name(doc) -> str:
	from smart_power.sp_core.services.company import get_company_settings

	settings = get_company_settings()
	return settings.legal_name_ar or settings.company or doc.get("company") or ""


def _customer_name(doc) -> str:
	return doc.get("customer_name") or doc.get("party_name") or doc.get("customer") or ""


def _total(doc) -> float:
	return flt(doc.get("rounded_total") or doc.get("grand_total") or doc.get("total") or doc.get("amount"))


def _system_type(doc) -> str:
	case = doc.get("sp_case")
	if not case:
		return ""
	system_type = frappe.db.get_value(
		"SP Case System Type", {"parent": case, "parenttype": "SP Case"}, "system_type", order_by="idx asc"
	)
	return cstr(frappe.db.get_value("SP List Value", system_type, "value_ar")) if system_type else ""


def resolvers() -> dict:
	"""placeholder -> how to read it from the document being printed."""
	return {
		"company_name": _company_name,
		"customer_name": _customer_name,
		"date": lambda doc: ar_date(
			doc.get("transaction_date") or doc.get("posting_date") or frappe.utils.today()
		),
		"total": lambda doc: money(_total(doc), doc.get("currency")),
		"total_words": lambda doc: ar_words(_total(doc)),
		"document_no": lambda doc: doc.get("name") or "",
		"quote_no": lambda doc: doc.get("name") or "",
		"version": lambda doc: cstr(doc.get("sp_version") or ""),
		"option": lambda doc: doc.get("sp_option_label") or "",
		"valid_till": lambda doc: ar_date(doc.get("valid_till")),
		"case_no": lambda doc: doc.get("sp_case") or "",
		"system_type": _system_type,
		"station_no": lambda doc: doc.get("sp_station") or doc.get("project") or "",
		"supplier_name": lambda doc: doc.get("supplier_name") or doc.get("supplier") or "",
		"amount": lambda doc: money(_total(doc), doc.get("currency")),
		"amount_words": lambda doc: ar_words(_total(doc)),
		"operation_date": lambda doc: ar_date(doc.get("sp_operation_date")),
		"balance": lambda doc: money(
			flt(doc.get("balance") or doc.get("outstanding_amount")), doc.get("currency")
		),
	}


COMMON = ("company_name", "customer_name", "date", "document_no")
PLACEHOLDERS = {
	"Quotation": (
		*COMMON,
		"quote_no",
		"version",
		"option",
		"valid_till",
		"case_no",
		"system_type",
		"total",
		"total_words",
	),
	"Contract": (*COMMON, "station_no", "case_no", "total", "total_words"),
	"Invoice": (*COMMON, "station_no", "total", "total_words"),
	"Receipt": (*COMMON, "station_no", "amount", "amount_words"),
	"Purchase Order": (
		"company_name",
		"date",
		"document_no",
		"supplier_name",
		"station_no",
		"total",
		"total_words",
	),
	"Transfer Note": ("company_name", "date", "document_no", "station_no"),
	"Return Note": ("company_name", "date", "document_no", "station_no", "supplier_name"),
	"Delivery Note": (*COMMON, "station_no"),
	"Warranty Certificate": (*COMMON, "station_no", "operation_date"),
	"Customer Statement": (*COMMON, "balance"),
}


def placeholders_of(document: str) -> tuple[str, ...]:
	return PLACEHOLDERS.get(document, COMMON)


def check_placeholders(document: str, text: str | None, where: str) -> None:
	"""Refuse a placeholder this document does not have, listing the valid ones."""
	valid = placeholders_of(document)
	unknown = sorted({name for name in PLACEHOLDER.findall(text or "") if name not in valid})
	if unknown:
		frappe.throw(
			_("{0}: unknown placeholder {1}. Valid placeholders: {2}").format(
				where,
				frappe.bold(", ".join("{" + u + "}" for u in unknown)),
				", ".join("{" + v + "}" for v in valid),
			),
			title=_("Check the placeholders"),
		)


def fill(text: str | None, doc) -> str:
	"""The text with each {placeholder} replaced by the document's value (HTML-escaped)."""
	doc = doc or frappe._dict()
	table = resolvers()

	def value(match):
		resolver = table.get(match.group(1))
		return str(escape(resolver(doc))) if resolver else match.group(0)

	return PLACEHOLDER.sub(value, text or "")


def published(document: str) -> str | None:
	return frappe.db.get_value(TEMPLATE, {"document": document, "is_published": 1}, "name")


def _blocks(document: str) -> list:
	name = published(document)
	if not name:
		return []
	return frappe.get_all(
		"SP Document Block",
		filters={"parent": name, "parenttype": TEMPLATE},
		fields=["block_key", "title", "body"],
		order_by="idx asc",
	)


def _render(block, doc) -> Markup:
	title = f'<h3 class="sp-block-title">{fill(escape(block.title), doc)}</h3>' if block.title else ""
	return Markup(f'<div class="sp-block sp-block-{block.block_key}">{title}{fill(block.body, doc)}</div>')


def sp_block(document: str, block_key: str, doc=None) -> Markup:
	"""One block of the document's published template, filled for doc (empty when missing)."""
	block = next((b for b in _blocks(document) if b.block_key == block_key), None)
	return _render(block, doc) if block else Markup("")


def sp_blocks(document: str, doc=None) -> list[Markup]:
	"""Every block of the document's published template, in order, filled for doc."""
	return [_render(block, doc) for block in _blocks(document)]


# --- the starting quote template ------------------------------------------------------------

QUOTE_BLOCKS = (
	(
		"preamble",
		"",
		"<p>السادة / {customer_name}</p><p>تحية طيبة وبعد،</p>"
		"<p>يسعد {company_name} أن تقدم لسيادتكم عرض السعر رقم {quote_no} (الخيار {option}، الإصدار {version}) "
		"لنظام {system_type}، بإجمالي {total} ({total_words}).</p>",
	),
	("execution_period", "مدة التنفيذ", "<p>تبدأ مدة التنفيذ من تاريخ استلام الدفعة المقدمة.</p>"),
	(
		"warranty",
		"الضمان",
		"<p>تسري مدة ضمان كل مكون من تاريخ التشغيل وفق ضمان الشركة المصنعة للمكون.</p>",
	),
	(
		"terms",
		"شروط العرض",
		"<p>هذا العرض ساري حتى {valid_till}. الأسعار شاملة التوريد والتركيب ما لم يُذكر غير ذلك.</p>",
	),
)


def seed_quote_template() -> None:
	"""Publish a first quote template once, so the quote PDF (SP-62) has text; then the admin's."""
	if frappe.db.exists(TEMPLATE, {"document": "Quotation"}):
		return
	doc = frappe.get_doc(
		{
			"doctype": TEMPLATE,
			"document": "Quotation",
			"blocks": [{"block_key": key, "title": title, "body": body} for key, title, body in QUOTE_BLOCKS],
		}
	).insert(ignore_permissions=True)
	doc.publish(check=False)
