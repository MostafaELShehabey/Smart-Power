"""Bank quote formats (SP-171, decision 52): the admin builds and changes them himself.

Al-Ahly and the Agri Bank each want their own quote layout, and they change what they ask for.
Both are seeded once as print format builder layouts on Quotation, from the banks' current
sheets (the Al-Ahly sheet in the quote workbook, the Agri Bank quote of 2-11-2026). They are not
standard formats and sit in the "Smart Power Admin" module (SP-164): the admin owns them from then on, copies them, drags fields onto them and
edits their text in the builder, with no code change. A migrate never overwrites them.

They are layouts of Frappe's new builder (`print_format_builder_beta`): the classic builder they
were first seeded with goes away in Frappe 17. A site that still holds the classic layouts gets
them converted once, by Frappe's own converter, with the admin's changes; the new builder prints
through other markup, so the layout options and the CSS below give it the sheet the classic
layout printed.

    bank_quote_table(doc, total_label)   the lines the bank sees (hidden lines out, merge groups
                                         as one line), numbered, with the total; for a Custom
                                         HTML block of a format
    set_total_in_words(doc)              Quotation validate: the total in Arabic words, a field
                                         the admin can drag onto any format
    seed_bank_formats()                  the two formats, once each
    convert_to_new_builder()             the classic layouts of an older site, moved to the new builder

The extra bank facts (water source, irrigation data, warranty, origin, year of manufacture) are
Quotation fields; the admin adds more in Customize Form and drags them on. Sending a version
(SP-61) stores the PDF as it was sent and the format it used, so a format changed later never
changes a quote already sent.
"""

import json

import frappe
from frappe.utils import cint, flt, fmt_money
from markupsafe import Markup, escape

from smart_power.constants import ADMIN_MODULE
from smart_power.sp_core.printing import ar_words

AL_AHLY, AGRI_BANK = "عرض سعر - البنك الأهلي", "عرض سعر - البنك الزراعي"
MONEY_DIGITS = 2  # sp-allow-number: currency precision


def _number(value) -> str:
	value = flt(value, MONEY_DIGITS)
	return fmt_money(value, precision=0 if value == cint(value) else MONEY_DIGITS)


def bank_quote_table(doc, total_label: str | None = None) -> Markup:
	"""م، البند، الوحدة، الكمية، سعر الوحدة، الإجمالي, then the discounts and the total."""
	from smart_power.sp_quotes.quote_print import quote_print

	data = quote_print(doc)
	head = "".join(
		f"<th>{h}</th>" for h in ("م", "البند", "الوحدة", "الكمية", "سعر الوحدة", "الإجمالي (جنيه)")
	)
	rows = []
	for idx, line in enumerate(data.lines, start=1):
		rows.append(
			"<tr>"
			f"<td class='sp-c'>{idx}</td>"
			f"<td>{escape(line.get('description') or '')}</td>"
			f"<td class='sp-c'>{escape(line.get('uom') or '')}</td>"
			f"<td class='sp-c'>{flt(line.get('qty')):g}</td>"
			f"<td class='sp-n'>{_number(line.get('rate'))}</td>"
			f"<td class='sp-n'>{_number(line.get('amount'))}</td>"
			"</tr>"
		)
	for discount in data.totals.discounts or []:
		rows.append(
			f"<tr><td colspan='5'>{escape(discount['label'])}</td>"
			f"<td class='sp-n'>- {_number(discount['amount'])}</td></tr>"
		)
	label = escape(total_label or "الإجمالي")
	rows.append(
		f"<tr class='sp-total'><td colspan='5'>{label}</td><td class='sp-n'>{_number(data.totals.total)}</td></tr>"
	)
	return Markup(
		f"<table class='sp-bank-table'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"
	)


def set_total_in_words(doc, method=None) -> None:
	"""Quotation validate: «فقط … لا غير» of the total, for any format to print."""
	total = flt(doc.get("rounded_total") or doc.get("grand_total"))
	doc.sp_total_in_words = f"فقط {ar_words(total)} لا غير" if total else ""


# --- the seeded formats ---------------------------------------------------------------------------

CSS = """
.print-format { direction: rtl; text-align: right; font-size: 12px; }
.sp-bank-heading { text-align: center; margin: 6px 0 12px; }
.sp-bank-heading .sp-bank-date { text-align: right; font-weight: bold; }
.sp-bank-heading h3 { font-size: 15px; text-decoration: underline; margin: 6px 0; }
.sp-bank-table { width: 100%; border-collapse: collapse; margin: 6px 0; }
.sp-bank-table th, .sp-bank-table td { border: 1px solid #333; padding: 4px 6px; }
.sp-bank-table th { background: #d9d9d9; text-align: center; }
.sp-bank-table .sp-c { text-align: center; }
.sp-bank-table .sp-n { text-align: left; direction: ltr; }
.sp-bank-table .sp-total td { font-weight: bold; background: #f2f2f2; }
.sp-bank-note { color: #c00; font-weight: bold; text-align: center; text-decoration: underline; }
.sp-bank-box { border: 1px solid #333; padding: 6px; margin: 4px 0; }
.sp-bank-sign { margin-top: 18px; font-weight: bold; text-decoration: underline; }
.print-format .section-label, .print-format h4 { background: #bfbfbf; padding: 3px 6px; }
"""

# The new builder prints through `.print-format-doc` markup with its own base styles (Inter, labels
# above values, underlined section headings). These rules give it the sheet the classic layout
# printed: the same fonts, sizes, colours, grey heading bars and label/value columns.
NEW_BUILDER_MARK = "/* the new builder: the sheet as the classic layout printed it */"
NEW_BUILDER_CSS = (
	NEW_BUILDER_MARK
	+ """
/* delete the next rule to print in the font chosen in the builder */
html, body { font-family: "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif; }
body.print-format-doc { direction: rtl; text-align: right; color: #36414c; line-height: 1.42857143; }
.print-format-doc .document-header-content { padding-top: 7px; }
.print-format-doc h3, .print-format-doc h4, .print-format-doc .section-label { font-weight: bold; line-height: 1.3em; color: inherit; }
.print-format-doc .section-label, .print-format-doc [document-status] h4 { background: #bfbfbf; padding: 3px 6px; border-bottom: 0; font-size: 16px; }
.print-format-doc .section-label { margin: 10px 0; }
.print-format-doc [document-status] { margin-bottom: 7px; }
.print-format-doc .sp-bank-table th { color: #74808b; font-weight: normal; }
.print-format-doc .sp-bank-table th, .print-format-doc .sp-bank-table td { vertical-align: top; }
.print-format-doc .section-columns > .col { padding-left: 0; padding-right: 0; }
.print-format-doc .field, .print-format-doc .field + .field { margin-top: 15px; line-height: 1.6; }
.print-format-doc .field .label, .print-format-doc .field.left-right .label { font-size: 13px; color: #4c5a67; margin-bottom: 0; }
.print-format-doc .field .value { color: #192734; line-height: 1.8; }
.print-format-doc .field.left-right { gap: 0; align-items: flex-start; }
.print-format-doc .field.left-right .label { flex: 0 0 calc((100% + 30px) * 0.4167); padding: 0; white-space: normal; }
.print-format-doc .field[data-fieldname="customer_name"] .value { font-size: 13px; font-weight: 600; }
"""
)

HEADING = (
	"<div class='sp-bank-heading'>"
	"<div class='sp-bank-date'>التاريخ : {{{{ ar_date(doc.transaction_date) }}}}</div>"
	"<h3>{title}{{% if doc.sp_irrigation_data %}} {{{{ doc.sp_irrigation_data }}}}{{% endif %}}</h3>"
	"</div>"
)
SIGNATURE = (
	"<div class='sp-bank-sign'>المدير العام</div>"
	"<div class='sp-bank-sign'>{{ get_company_settings().owner_name or '' }}</div>"
)
NOTE = "<div class='sp-bank-note'>ملحوظة : الأسعار لا تشمل أي ضرائب ولا تشمل الأعمال المدنية</div>"

COLUMN_GUTTER = 30  # sp-allow-number: px between two columns, as the classic layout's grid
STACKED_FROM = 3  # sp-allow-number: from three columns on the classic layout put the label above the value
# what the classic layout printed whatever the format's own settings said: 12px text (its CSS), and
# the letterhead and footer at the paper's edge (the classic Chrome PDF ignored these two margins)
CLASSIC_LOOK = {"font_size": 12, "show_label_colon": 1, "margin_top": 0, "margin_bottom": 0}  # sp-allow-number: see above

# each field with the banks' own wording and its type; the admin changes a label in the builder
FIELDS = {
	"customer_name": ("اسم العميل", "Data"),
	"sp_customer_mobile": ("رقم تليفون العميل", "Data"),
	"sp_site": ("الموقع ومكان التسليم", "Data"),
	"sp_water_source": ("مصدر المياه", "Data"),
	"sp_total_in_words": ("الإجمالي بالحروف", "Small Text"),
	"valid_till": ("صلاحية العرض حتى", "Date"),
	"sp_execution_period": ("مدة التنفيذ", "Data"),
	"sp_warranty": ("الضمان", "Data"),
	"sp_origin": ("بلد المنشأ", "Data"),
	"sp_manufacture_year": ("سنة الصنع", "Data"),
}


def _field(fieldname: str) -> dict:
	label, fieldtype = FIELDS[fieldname]
	return {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "options": None}


def _html(html: str) -> dict:
	"""A Custom HTML block (Jinja); `_layout` numbers it."""
	return {"label": "Custom HTML", "fieldtype": "HTML", "html": html, "custom": 1}


def _section(label: str, *columns: list) -> dict:
	return {"label": label, "columns": [{"label": "", "fields": fields} for fields in columns]}


def keep_classic_look(layout: dict) -> dict:
	"""The classic sheet on the new builder: the label beside its value (above it from three
	columns on), the classic gutter between columns, and no extra gap between sections."""
	for section in layout.get("sections") or []:
		section["gap"] = COLUMN_GUTTER
		section["margin"] = {"top": 0, "right": 0, "bottom": 0, "left": 0}
		if len(section.get("columns") or []) < STACKED_FROM:
			section["field_orientation"] = "left-right"
	return layout


def _layout(title: str, *sections: dict) -> dict:
	"""A layout of the new builder: the heading (with its Jinja) on top of every page, then the sections."""
	blocks = [
		field
		for section in sections
		for column in section["columns"]
		for field in column["fields"]
		if field["fieldtype"] == "HTML"
	]
	for number, block in enumerate(blocks, start=1):
		block["fieldname"] = f"custom_html_{number}"
	heading = {
		"label": "",
		"fieldname": "print_heading_template",
		"fieldtype": "HTML",
		"html": HEADING.format(title=title),
		"custom": 1,
	}
	return keep_classic_look(
		{
			"sections": list(sections),
			"header": {"columns": [{"label": "", "fields": [heading]}]},
			"footer": {"columns": [{"label": "", "fields": []}]},
		}
	)


def _al_ahly() -> dict:
	return _layout(
		"عرض سعر توريد وتركيب شبكات ري حديثة + محطة طاقة شمسية",
		_section("بيانات العميل", [_field("customer_name")], [_field("sp_customer_mobile")]),
		_section("بيانات المحطة", [_field("sp_site")], [_field("sp_water_source")]),
		_section(
			"",
			[
				_html("{{ bank_quote_table(doc, 'الإجمالي ( طاقة شمسية + شبكات ري )') }}"),
				_field("sp_total_in_words"),
				_html(NOTE),
			],
		),
		_section(
			"",
			[
				_html("<div class='sp-bank-box'><b>طريقة الدفع</b><br>تحويلات بنكية</div>"),
				_field("valid_till"),
				_field("sp_origin"),
			],
			[_field("sp_warranty"), _field("sp_execution_period"), _field("sp_manufacture_year")],
		),
		_section("", [], [_html(SIGNATURE)]),
	)


def _agri_bank() -> dict:
	payment = (
		"<div class='sp-bank-box'><b>طريقة الدفع : تحويلات بنكية</b><br>"
		"على أن يتم الدفع على حساب الشركة ببنك ……… رقم الحساب : ………</div>"
	)
	return _layout(
		"عرض سعر توريد وتركيب محطة طاقة شمسية شاملة الموتور والطلمبة ومشتملات تشغيل البئر",
		_section("بيانات العميل", [_field("customer_name")], [_field("sp_customer_mobile")]),
		_section("بيانات المحطة", [_field("sp_site")], [_field("sp_water_source")]),
		_section(
			"",
			[
				_html("{{ bank_quote_table(doc, 'الإجمالي ( طاقة شمسية + غاطس )') }}"),
				_field("sp_total_in_words"),
				_html(NOTE),
			],
		),
		_section("", [_html(payment), _field("valid_till"), _field("sp_execution_period")]),
		_section("", [_field("sp_origin")], [_field("sp_manufacture_year")], [_field("sp_warranty")]),
		_section("", [], [_html(SIGNATURE)]),
	)


FORMATS = {AL_AHLY: _al_ahly, AGRI_BANK: _agri_bank}


def seed_bank_formats() -> list[str]:
	"""Each bank's format, once. The admin owns it afterwards: never overwritten."""
	made = []
	for name, layout in FORMATS.items():
		if frappe.db.exists("Print Format", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": name,
				"doc_type": "Quotation",
				"module": ADMIN_MODULE,  # the admin's own (SP-164): copied, edited, backed up nightly
				"standard": "No",
				"custom_format": 0,
				"print_format_builder": 0,
				"print_format_builder_beta": 1,
				"print_format_type": "Jinja",
				"default_print_language": "ar",
				"pdf_generator": "chrome",
				"page_number": "Bottom Center",
				**CLASSIC_LOOK,
				"format_data": json.dumps(layout(), ensure_ascii=False),
				"css": CSS + NEW_BUILDER_CSS,
			}
		).insert(ignore_permissions=True)
		made.append(name)
	return made


def convert_to_new_builder(only: list[str] | None = None) -> list[str]:
	"""The classic layouts an older site holds (the two seeded ones and the admin's copies of
	them, or `only` the named ones) move to the new builder, with whatever the admin changed in them.

	Frappe's own converter does the move, as its "Convert to new builder" button would, and keeps
	the classic layout on the format ("Restore classic layout" brings it back). On top of it the
	layout options and the CSS keep the sheet as it printed. A format already converted is left alone."""
	try:
		from frappe.printing.doctype.print_format.classic_converter import convert_print_format
	except ImportError:  # a Frappe without the classic layouts has nothing to convert
		return []

	filters = {
		"module": ADMIN_MODULE,
		"standard": "No",
		"custom_format": 0,
		"print_format_builder": 1,
		"print_format_builder_beta": 0,
		"css": ("like", "%.sp-bank-table%"),  # the banks' sheet
	}
	if only is not None:
		filters["name"] = ("in", only)
	names = frappe.get_all("Print Format", filters=filters, pluck="name")
	moved = []
	for name in names:
		doc = frappe.get_doc("Print Format", name)
		if convert_print_format(doc) is None:  # not a classic layout after all
			continue
		doc.format_data = json.dumps(keep_classic_look(json.loads(doc.format_data)), ensure_ascii=False)
		doc.update(CLASSIC_LOOK)
		if NEW_BUILDER_MARK not in (doc.css or ""):
			doc.css = (doc.css or "").rstrip("\n") + "\n" + NEW_BUILDER_CSS
		doc.save(ignore_permissions=True)
		moved.append(name)
	return moved
