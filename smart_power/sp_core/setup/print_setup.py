"""Printing defaults (SP-23): the "Smart Power" letterhead and Chrome PDFs on A4.

Run once (install and the sp23 patch). After that the letterhead and Print Settings are the
admin's: a deploy never overwrites them.
"""

import frappe

LETTER_HEAD = "Smart Power"
# ERPNext's setup wizard makes these; they never carry Smart Power's legal data
STOCK_LETTER_HEADS = ("Company Letterhead", "Company Letterhead - Grey")
PDF_GENERATOR = "chrome"  # Arabic letters join correctly; wkhtmltopdf is not installed
PAGE_SIZE = "A4"


def _template(name: str) -> str:
	return frappe.read_file(frappe.get_app_path("smart_power", "templates", "print", name))


def setup_printing() -> None:
	ensure_letter_head()
	ps = frappe.get_single("Print Settings")
	ps.pdf_generator = PDF_GENERATOR
	ps.pdf_page_size = PAGE_SIZE
	ps.repeat_header_footer = 1
	ps.flags.ignore_permissions = True
	ps.save()


def ensure_letter_head() -> None:
	"""Create the letterhead once; it becomes the default unless the admin chose another one."""
	if not frappe.db.exists("Letter Head", LETTER_HEAD):
		create_letter_head()
	default = frappe.db.get_value("Letter Head", {"is_default": 1})
	if not default or default in STOCK_LETTER_HEADS:
		if default:
			frappe.db.set_value("Letter Head", default, "is_default", 0)
		frappe.db.set_value("Letter Head", LETTER_HEAD, "is_default", 1)


def create_letter_head() -> None:
	frappe.get_doc(
		{
			"doctype": "Letter Head",
			"letter_head_name": LETTER_HEAD,
			"source": "HTML",
			"content": _template("letterhead_header.html"),
			"footer_source": "HTML",
			"footer": _template("letterhead_footer.html"),
		}
	).insert(ignore_permissions=True)
