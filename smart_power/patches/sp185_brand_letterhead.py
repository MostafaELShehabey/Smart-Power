"""SP-185: the brand letterhead (navy and orange, as on the company's own paper).

The "Smart Power" letterhead is replaced only while it is still exactly what the app made (SP-23 or
SP-62). A letterhead the admin edited is left alone: the new design is then added beside it as
"Smart Power (2026)", and the admin chooses which one is the default.

Company settings get the brand names and the tagline the new header prints.
"""

import frappe

from smart_power.patches.sp62_letterhead_sizes import OLD_HEADER as SP23_HEADER
from smart_power.sp_core.setup.print_setup import adopt_brand_letter_head, seed_brand_names

# the header as SP-62 left it, and the footer as SP-23 made it
SP62_HEADER = '{%- set company = get_company_settings() -%}\n<style class="sp-letterhead-style">\n\t/* the letterhead\'s own sizes, so any print format (ERPNext\'s too) shows it right */\n\t.sp-letterhead { direction: rtl; font-family: "IBM Plex Sans Arabic", sans-serif; }\n\t.sp-letterhead-table { width: 100%; border-bottom: 2px solid #c8a24a; }\n\t.sp-letterhead-logo { width: 90px; }\n\t.sp-letterhead-logo img { max-height: 60px; max-width: 90px; }\n\t.sp-legal-name { font-size: 16px; font-weight: 700; color: #0b2e59; }\n\t.sp-legal-line { font-size: 11px; color: #4a5568; }\n</style>\n<div class="sp-letterhead" dir="rtl">\n\t<table class="sp-letterhead-table">\n\t\t<tr>\n\t\t\t<td class="sp-letterhead-logo"><img src="{{ embed_image(company_logo()) }}" alt=""></td>\n\t\t\t<td class="sp-letterhead-name">\n\t\t\t\t<div class="sp-legal-name">{{ company.legal_name_ar or company.company or "" }}</div>\n\t\t\t\t{%- if company.commercial_register %}\n\t\t\t\t<div class="sp-legal-line">{{ _("Commercial Register") }}: <span class="sp-num">{{ company.commercial_register }}</span></div>\n\t\t\t\t{%- endif %}\n\t\t\t\t{%- if company.tax_card %}\n\t\t\t\t<div class="sp-legal-line">{{ _("Tax Card") }}: <span class="sp-num">{{ company.tax_card }}</span></div>\n\t\t\t\t{%- endif %}\n\t\t\t</td>\n\t\t</tr>\n\t</table>\n</div>\n'
SP23_FOOTER = '<div class="sp-letterfoot" dir="rtl">\n\t<div class="sp-addresses">\n\t\t{%- for row in company_addresses() %}\n\t\t<span class="sp-address">{{ row.label or "" }}{% if row.address %}: {{ row.address }}{% endif %}{% if row.phone %} · <span class="sp-num">{{ row.phone }}</span>{% endif %}</span>\n\t\t{%- endfor %}\n\t</div>\n\t<div class="sp-page-no">{{ _("Page") }} <span class="page"></span> {{ _("of") }} <span class="topage"></span></div>\n</div>\n'


def execute():
	frappe.reload_doc("sp_core", "doctype", "sp_company_settings")
	seed_brand_names()
	adopt_brand_letter_head(headers=(SP23_HEADER, SP62_HEADER), footers=(SP23_FOOTER,))
