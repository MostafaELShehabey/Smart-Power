"""The brand letterhead on every printed document (SP-185).

The header and footer are the two templates in `templates/print/` (drawn from the company's own
paper). This module gives them their data, and makes a Chrome PDF print them edge to edge: Chrome
clips a header to the page's side margins, so a PDF that carries our letterhead gets no side
margins and its body gets them back as padding.
"""

import re

import frappe
from bs4 import BeautifulSoup

from smart_power.sp_core.printing import embed_image, print_fonts
from smart_power.sp_core.services.company import company_addresses, company_logo, get_company_settings

BRAND_EN = "Smart Power"
BRAND_AR = "سمارت باور"
TAGLINE_AR = "لأنظمة الطاقة الشمسية والمقاولات"
BRAND_DEFAULTS = {"brand_name_en": BRAND_EN, "brand_name_ar": BRAND_AR, "tagline_ar": TAGLINE_AR}

MARK = "sp-lh"  # the class on our header and footer
PAGE_STYLE_ID = "sp-lh-page"
FONT = "IBM Plex Sans Arabic"
SIDE_MARGIN = "15mm"  # Frappe's side margin when a format sets none
SIDES = ("margin-left", "margin-right")
# the header owns the paper's top edge and the footer its bottom edge
EDGE = {"header-html": "margin-top", "footer-html": "margin-bottom"}
BUILDER_BODY = "print-format-doc"  # the <body> class of a layout of Frappe's new builder
# an @page rule, with the margin boxes it may hold (@bottom-center { ... })
PAGE_RULE = re.compile(r"@page[^{]*\{(?:[^{}]|\{[^{}]*\})*\}")
# what fits on the footer bar beside the addresses
MAX_PHONES = 2  # sp-allow-number: rows of the footer's contact block
MAX_ADDRESSES = 3  # sp-allow-number: rows of the footer's address block


def letterhead() -> dict:
	"""What the letterhead templates print, from Company settings (X12)."""
	company = get_company_settings()
	rows = company_addresses()
	phones = list(dict.fromkeys((row["phone"] or "").strip() for row in rows if (row["phone"] or "").strip()))
	contacts = [{"kind": "phone", "text": phone} for phone in phones[:MAX_PHONES]]
	if company.get("email"):
		contacts.append({"kind": "email", "text": company.email})
	addresses = [
		{"text": ": ".join(part for part in (row["label"], row["address"]) if part)}
		for row in rows
		if row["label"] or row["address"]
	]
	return {
		"logo": embed_image(company_logo()),
		"name_en": company.get("brand_name_en") or BRAND_EN,
		"name_ar": company.get("brand_name_ar") or BRAND_AR,
		"tagline": company.get("tagline_ar") or TAGLINE_AR,
		"contacts": contacts,
		"addresses": addresses[:MAX_ADDRESSES],
	}


# --- Chrome PDFs: the header and footer pages (hooks pdf_header_html and pdf_footer_html) ---------


def pdf_header_html(soup, head, content, styles, html_id, css, path=None):
	"""Frappe's header (or footer) page; with our letterhead in it, the PDF goes edge to edge."""
	from frappe.utils.pdf import pdf_header_html as frappe_header_html

	if content.find(class_=MARK):
		left, right = edge_to_edge(soup, html_id)
		drop_other_page_numbers(content)
		# what a format prints beside our letterhead (a heading on every page) keeps the side
		# margins; a layout of the new builder fixes the <body> to the width inside its margins
		own = (
			"html > body { min-width: 0 !important; max-width: none !important; } "
			".wrapper > :not(.letter-head):not(.letter-head-footer):not(style):not(script) "
			f"{{ box-sizing: border-box; padding-left: {left}; padding-right: {right}; }}"
		)
		styles = [*with_fonts(styles), _style(own)]
	return frappe_header_html(
		soup=soup, head=head, content=content, styles=styles, html_id=html_id, css=css, path=path
	)


def pdf_footer_html(soup, head, content, styles, html_id, css, path=None):
	return pdf_header_html(
		soup=soup, head=head, content=content, styles=styles, html_id=html_id, css=css, path=path
	)


def _style(css: str, **attrs):
	tag = BeautifulSoup("<style></style>", "html.parser").style
	tag.string = css
	tag.attrs.update(attrs)
	return tag


def edge_to_edge(soup, html_id: str) -> tuple[str, str]:
	"""No margins around our header or footer; the body keeps its side margins as padding, and
	they are returned (left, right).

	Chrome clips a header to the page's side margins, so the pages get none. Frappe reads a
	PDF's margins from the `.print-format` rules of the document's styles after the header and
	footer are taken out, so the rule is added to the document itself: to its body, as the header
	and footer pages are given the document's <head> and must not get the padding. A layout of
	the new builder also states its margins in an @page rule, which Chrome obeys on every page
	(the header's and footer's too): those margins are set to zero in the rule itself."""
	from frappe.utils.pdf import get_print_format_styles
	from frappe.www.printview import get_page_rule_margins

	edge = EDGE.get(html_id)
	page_style = soup.find("style", id=PAGE_STYLE_ID)
	if not page_style:
		margins = dict.fromkeys(SIDES, SIDE_MARGIN)
		css = "".join(tag.string or "" for tag in soup.find_all("style"))
		margins.update({side: value for side, value in get_page_rule_margins(css).items() if side in SIDES})
		margins.update(
			{rule.name: rule.value.strip() for rule in get_print_format_styles(soup) if rule.name in SIDES}
		)
		left, right = (margins[side] for side in SIDES)
		builder = soup.body and BUILDER_BODY in (soup.body.get("class") or [])
		# the builder fixes its <body> to the width inside the margins: it gets the whole page back
		body = f"html > body.{BUILDER_BODY}" if builder else ".print-format"
		width = "min-width: 0 !important; max-width: none !important; " if builder else ""
		page_style = _style(
			".print-format { margin-left: 0mm; margin-right: 0mm; } "
			f"{body} {{ box-sizing: border-box; {width}padding-left: {left} !important; "
			f"padding-right: {right} !important; }}",
			id=PAGE_STYLE_ID,
			**{"data-left": left, "data-right": right},
		)
		(soup.body or soup).append(page_style)
		no_page_rule_margins(soup, SIDES)
	if edge and not soup.find("style", id=f"{PAGE_STYLE_ID}-{html_id}"):
		(soup.body or soup).append(
			_style(f".print-format {{ {edge}: 0mm; }}", id=f"{PAGE_STYLE_ID}-{html_id}")
		)
		no_page_rule_margins(soup, (edge,))
	return page_style["data-left"], page_style["data-right"]


def no_page_rule_margins(soup, sides: tuple[str, ...]) -> None:
	"""Zero the given margins inside the document's @page rules."""
	margin = re.compile(rf"\b({'|'.join(sides)})\s*:\s*[^;}}]+")
	for tag in soup.find_all("style"):
		css = tag.string or ""
		if "@page" in css:
			tag.string = PAGE_RULE.sub(lambda rule: margin.sub(r"\1: 0", rule.group(0)), css)


def drop_other_page_numbers(content) -> None:
	"""Our footer numbers the pages above its bar: a second page line under it (ERPNext's formats
	and the new builder add one) would lift the bar off the paper's edge."""
	if not content.find(class_="sp-lh-pageno"):
		return
	for number in content.find_all(class_="page"):
		if number.parent is not None and not number.find_parent(class_=MARK):
			number.parent.decompose()


def with_fonts(styles: list) -> list:
	"""The header and footer pages load nothing: give them the embedded font when the document's
	own styles don't carry it (ERPNext's formats, reports)."""
	if any(f"font-family:'{FONT}'" in (tag.string or "") for tag in styles):
		return styles
	return [*styles, _style(print_fonts())]
