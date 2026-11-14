"""SP-62: the Smart Power letterhead carries its own sizes, so the logo is not huge on print
formats other than Smart Power's. Only a letterhead still exactly as the app made it is updated;
an admin's edited letterhead is left alone."""

import frappe

from smart_power.sp_core.setup.print_setup import LETTER_HEAD, _template

# the header exactly as SP-23 created it
OLD_HEADER = '{%- set company = get_company_settings() -%}\n<div class="sp-letterhead" dir="rtl">\n\t<table class="sp-letterhead-table">\n\t\t<tr>\n\t\t\t<td class="sp-letterhead-logo"><img src="{{ embed_image(company_logo()) }}" alt=""></td>\n\t\t\t<td class="sp-letterhead-name">\n\t\t\t\t<div class="sp-legal-name">{{ company.legal_name_ar or company.company or "" }}</div>\n\t\t\t\t{%- if company.commercial_register %}\n\t\t\t\t<div class="sp-legal-line">{{ _("Commercial Register") }}: <span class="sp-num">{{ company.commercial_register }}</span></div>\n\t\t\t\t{%- endif %}\n\t\t\t\t{%- if company.tax_card %}\n\t\t\t\t<div class="sp-legal-line">{{ _("Tax Card") }}: <span class="sp-num">{{ company.tax_card }}</span></div>\n\t\t\t\t{%- endif %}\n\t\t\t</td>\n\t\t</tr>\n\t</table>\n</div>\n'


def execute():
	if not frappe.db.exists("Letter Head", LETTER_HEAD):
		return
	content = frappe.db.get_value("Letter Head", LETTER_HEAD, "content") or ""
	if content.strip() == OLD_HEADER.strip():
		frappe.db.set_value("Letter Head", LETTER_HEAD, "content", _template("letterhead_header.html"))
