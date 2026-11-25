"""Printing defaults (SP-23): the "Smart Power" letterhead and Chrome PDFs on A4.

Run once (install and the sp23 patch). After that the letterhead and Print Settings are the
admin's: a deploy never overwrites them. The letterhead's design is the brand one (SP-185).
"""

import frappe

LETTER_HEAD = "Smart Power"
# the brand design beside a letterhead the admin edited (SP-185)
BRAND_LETTER_HEAD = "Smart Power (2026)"
COMPANY_SETTINGS = "SP Company Settings"
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
	"""Create the letterhead once; it becomes the default unless the admin chose another one.

	It is made default through the Letter Head record, so Frappe also moves the site's default
	letterhead (which ERPNext copies onto every new quote), not only the "Default" tick."""
	if not frappe.db.exists("Letter Head", LETTER_HEAD):
		create_letter_head()
	ours_or_stock = (None, "", LETTER_HEAD, *STOCK_LETTER_HEADS)
	ticked = frappe.db.get_value("Letter Head", {"is_default": 1})
	site_default = frappe.db.get_default("letter_head")
	if ticked not in ours_or_stock or site_default not in ours_or_stock:
		return  # the admin's own choice
	if ticked == LETTER_HEAD and site_default == LETTER_HEAD:
		return
	doc = frappe.get_doc("Letter Head", LETTER_HEAD)
	doc.is_default = 1
	doc.flags.ignore_permissions = True
	doc.save()


def use_our_letter_head_on_drafts() -> None:
	"""Draft quotes that still carry ERPNext's stock letterhead print with Smart Power's."""
	frappe.db.set_value(
		"Quotation",
		{"docstatus": 0, "letter_head": ("in", list(STOCK_LETTER_HEADS))},
		"letter_head",
		LETTER_HEAD,
		update_modified=False,
	)


def create_letter_head(name: str = LETTER_HEAD) -> None:
	frappe.get_doc(
		{
			"doctype": "Letter Head",
			"letter_head_name": name,
			"source": "HTML",
			"content": _template("letterhead_header.html"),
			"footer_source": "HTML",
			"footer": _template("letterhead_footer.html"),
		}
	).insert(ignore_permissions=True)


def adopt_brand_letter_head(headers: tuple[str, ...], footers: tuple[str, ...]) -> str | None:
	"""Give an existing site the brand letterhead (SP-185); returns the letterhead that got it.

	headers, footers: what the app itself put in "Smart Power" before. While the letterhead is
	still one of those, it is replaced. One the admin edited is kept as it is, default or not, and
	the brand design is added beside it for the admin to choose."""
	if not frappe.db.exists("Letter Head", LETTER_HEAD):
		return None  # a new site: setup_printing() makes it
	header, footer = _template("letterhead_header.html"), _template("letterhead_footer.html")
	content, old_footer = frappe.db.get_value("Letter Head", LETTER_HEAD, ["content", "footer"])
	if (content or "").strip() == header.strip() and (old_footer or "").strip() == footer.strip():
		return LETTER_HEAD
	app_made = (content or "").strip() in {h.strip() for h in headers}
	app_made = app_made and (old_footer or "").strip() in {f.strip() for f in footers}
	if app_made:
		frappe.db.set_value("Letter Head", LETTER_HEAD, {"content": header, "footer": footer})
		return LETTER_HEAD
	if not frappe.db.exists("Letter Head", BRAND_LETTER_HEAD):
		create_letter_head(BRAND_LETTER_HEAD)
	return BRAND_LETTER_HEAD


def seed_brand_names() -> None:
	"""The names and tagline under the header bar, where Company settings has none yet."""
	from smart_power.sp_core.letterhead import BRAND_DEFAULTS

	for field, value in BRAND_DEFAULTS.items():
		if not frappe.db.get_single_value(COMPANY_SETTINGS, field):
			frappe.db.set_single_value(COMPANY_SETTINGS, field, value)
	frappe.clear_document_cache(COMPANY_SETTINGS, COMPANY_SETTINGS)
