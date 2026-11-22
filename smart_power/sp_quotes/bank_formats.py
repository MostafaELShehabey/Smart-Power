"""Bank quote formats (SP-171, decision 52): the admin builds and changes them himself.

Al-Ahly and the Agri Bank each want their own quote layout, and they change what they ask for.
Both are seeded once as Print Format Builder layouts on Quotation, from the banks' current
sheets (the Al-Ahly sheet in the quote workbook, the Agri Bank quote of 2-11-2026). They are not
standard formats and sit in the "Smart Power Admin" module (SP-164): the admin owns them from then on, copies them, drags fields onto them and
edits their text in the builder, with no code change. A migrate never overwrites them.

    bank_quote_table(doc, total_label)   the lines the bank sees (hidden lines out, merge groups
                                         as one line), numbered, with the total; for a Custom
                                         HTML block of a format
    set_total_in_words(doc)              Quotation validate: the total in Arabic words, a field
                                         the admin can drag onto any format
    seed_bank_formats()                  the two formats, once each

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


def _html(options: str) -> dict:
	return {
		"fieldname": "_custom_html",
		"fieldtype": "HTML",
		"label": "Custom HTML",
		"print_hide": 0,
		"options": options,
	}


# the banks' own wording for each field; the admin changes a label in the builder
LABELS = {
	"customer_name": "اسم العميل",
	"sp_customer_mobile": "رقم تليفون العميل",
	"sp_site": "الموقع ومكان التسليم",
	"sp_water_source": "مصدر المياه",
	"sp_total_in_words": "الإجمالي بالحروف",
	"valid_till": "صلاحية العرض حتى",
	"sp_execution_period": "مدة التنفيذ",
	"sp_warranty": "الضمان",
	"sp_origin": "بلد المنشأ",
	"sp_manufacture_year": "سنة الصنع",
}


def _field(fieldname: str) -> dict:
	return {"fieldname": fieldname, "label": LABELS.get(fieldname), "print_hide": 0}


def _section(label: str = "") -> list[dict]:
	return [{"fieldtype": "Section Break", "label": label}, {"fieldtype": "Column Break"}]


COLUMN = {"fieldtype": "Column Break"}


def _al_ahly() -> list[dict]:
	title = "عرض سعر توريد وتركيب شبكات ري حديثة + محطة طاقة شمسية"
	return [
		{
			"fieldname": "print_heading_template",
			"fieldtype": "Custom HTML",
			"options": HEADING.format(title=title),
		},
		*_section("بيانات العميل"),
		_field("customer_name"),
		COLUMN,
		_field("sp_customer_mobile"),
		*_section("بيانات المحطة"),
		_field("sp_site"),
		COLUMN,
		_field("sp_water_source"),
		*_section(),
		_html("{{ bank_quote_table(doc, 'الإجمالي ( طاقة شمسية + شبكات ري )') }}"),
		_field("sp_total_in_words"),
		_html("<div class='sp-bank-note'>ملحوظة : الأسعار لا تشمل أي ضرائب ولا تشمل الأعمال المدنية</div>"),
		*_section(),
		_html("<div class='sp-bank-box'><b>طريقة الدفع</b><br>تحويلات بنكية</div>"),
		_field("valid_till"),
		_field("sp_origin"),
		COLUMN,
		_field("sp_warranty"),
		_field("sp_execution_period"),
		_field("sp_manufacture_year"),
		*_section(),
		COLUMN,
		_html(SIGNATURE),
	]


def _agri_bank() -> list[dict]:
	title = "عرض سعر توريد وتركيب محطة طاقة شمسية شاملة الموتور والطلمبة ومشتملات تشغيل البئر"
	payment = (
		"<div class='sp-bank-box'><b>طريقة الدفع : تحويلات بنكية</b><br>"
		"على أن يتم الدفع على حساب الشركة ببنك ……… رقم الحساب : ………</div>"
	)
	return [
		{
			"fieldname": "print_heading_template",
			"fieldtype": "Custom HTML",
			"options": HEADING.format(title=title),
		},
		*_section("بيانات العميل"),
		_field("customer_name"),
		COLUMN,
		_field("sp_customer_mobile"),
		*_section("بيانات المحطة"),
		_field("sp_site"),
		COLUMN,
		_field("sp_water_source"),
		*_section(),
		_html("{{ bank_quote_table(doc, 'الإجمالي ( طاقة شمسية + غاطس )') }}"),
		_field("sp_total_in_words"),
		_html("<div class='sp-bank-note'>ملحوظة : الأسعار لا تشمل أي ضرائب ولا تشمل الأعمال المدنية</div>"),
		*_section(),
		_html(payment),
		_field("valid_till"),
		_field("sp_execution_period"),
		*_section(),
		_field("sp_origin"),
		COLUMN,
		_field("sp_manufacture_year"),
		COLUMN,
		_field("sp_warranty"),
		*_section(),
		COLUMN,
		_html(SIGNATURE),
	]


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
				"print_format_builder": 1,
				"print_format_type": "Jinja",
				"default_print_language": "ar",
				"pdf_generator": "chrome",
				"show_section_headings": 1,
				"line_breaks": 0,
				"format_data": json.dumps(layout(), ensure_ascii=False),
				"css": CSS,
			}
		).insert(ignore_permissions=True)
		made.append(name)
	return made
