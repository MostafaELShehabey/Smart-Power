"""Helpers for printed documents (SP-23), available in every print format and letterhead.

    money(125450.5)           "125,450.50 EGP" (the site's money format)
    ar_words(125450.5)        "مائة خمسة وعشرون ألفاً وأربعمائة خمسون جنيهاً وخمسون قرشاً"
    ar_date("2026-11-14")     "14 نوفمبر 2026"
    signature_block("المستلم", "المدير")   signature boxes
    qr(url)                   a QR code image (e.g. to verify a receipt)

Amounts in words (تفقيط) follow the style of the story's example: within each group the
hundreds come first, then the units and tens ("مائة خمسة وعشرون"); groups are joined with "و";
the counted word agrees with the number (ألف، ألفان، آلاف، ألفاً; جنيه، جنيهان، جنيهات، جنيهاً).
"""

import functools

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, getdate
from markupsafe import Markup, escape

TEN, THOUSAND = 10, 1000  # sp-allow-number: number words, not business values
UNITS = ("", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة")
TEENS = (
	"عشرة",
	"أحد عشر",
	"اثنا عشر",
	"ثلاثة عشر",
	"أربعة عشر",
	"خمسة عشر",
	"ستة عشر",
	"سبعة عشر",
	"ثمانية عشر",
	"تسعة عشر",
)
TENS = ("", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون")
HUNDREDS = (
	"",
	"مائة",
	"مائتان",
	"ثلاثمائة",
	"أربعمائة",
	"خمسمائة",
	"ستمائة",
	"سبعمائة",
	"ثمانمائة",
	"تسعمائة",
)
# (one, two, three to ten, eleven and up) for each counted word
THOUSANDS = ("ألف", "ألفان", "آلاف", "ألفاً")
MILLIONS = ("مليون", "مليونان", "ملايين", "مليوناً")
BILLIONS = ("مليار", "ملياران", "مليارات", "ملياراً")
POUNDS = ("جنيه", "جنيهان", "جنيهات", "جنيهاً")
PIASTERS = ("قرش", "قرشان", "قروش", "قرشاً")
SCALES = (None, THOUSANDS, MILLIONS, BILLIONS)
ZERO = "صفر"
JOIN = " و"
MONTHS = (
	"يناير",
	"فبراير",
	"مارس",
	"أبريل",
	"مايو",
	"يونيو",
	"يوليو",
	"أغسطس",
	"سبتمبر",
	"أكتوبر",
	"نوفمبر",
	"ديسمبر",
)


def below_thousand(n: int) -> str:
	"""1 to 999 in words: the hundreds, then the units and tens ("مائة خمسة وعشرون")."""
	hundreds, rest = divmod(n, 100)
	parts = [HUNDREDS[hundreds]] if hundreds else []
	if rest >= TEN * 2:  # sp-allow-number: twenty and up
		tens, units = divmod(rest, TEN)
		parts.append(f"{UNITS[units]} و{TENS[tens]}" if units else TENS[tens])
	elif rest >= TEN:
		parts.append(TEENS[rest - TEN])
	elif rest:
		parts.append(UNITS[rest])
	return " ".join(parts)


def counted(n: int, forms: tuple[str, str, str, str], construct: bool = False) -> str:
	"""A number with its counted word: ألف، ألفان، ثلاثة آلاف، أحد عشر ألفاً، مائة ألف.

	construct: another word follows (ألف جنيه، ألفا جنيه، أحد عشر ألف جنيه)."""
	one, two, few, many = forms
	if construct:
		two, many = two.removesuffix("ن"), one
	if n == 1:
		return one
	if n == 2:  # sp-allow-number: the Arabic dual
		return two
	last_two = n % 100
	words = number_words(n, construct=True)
	if 3 <= last_two <= TEN:  # sp-allow-number: Arabic plural range 3-10
		return f"{words} {few}"
	if last_two > TEN:
		return f"{words} {many}"
	return f"{words} {one}"


def number_words(n: int, construct: bool = False) -> str:
	"""A whole number in words, e.g. 125450 → "مائة خمسة وعشرون ألفاً وأربعمائة خمسون".

	construct: a counted word follows, so a closing ألف/مليون takes its construct form."""
	if n == 0:
		return ZERO
	groups = []
	scale = 0
	while n:
		n, group = divmod(n, THOUSAND)
		if group:
			forms = SCALES[scale]
			last = construct and not groups
			groups.append(counted(group, forms, construct=last) if forms else below_thousand(group))
		scale += 1
	return JOIN.join(reversed(groups))


def ar_words(value, with_currency: bool = True) -> str:
	"""An amount in Egyptian pounds and piasters in words (تفقيط)."""
	cents = round(abs(flt(value, 2)) * 100)  # sp-allow-number: piasters
	pounds, piasters = divmod(cents, 100)
	if not with_currency:
		return number_words(pounds)
	parts = []
	if pounds or not piasters:
		parts.append(counted(pounds, POUNDS) if pounds else f"{ZERO} {POUNDS[0]}")
	if piasters:
		parts.append(counted(piasters, PIASTERS))
	return JOIN.join(parts)


def money(value, currency: str | None = None) -> str:
	"""An amount with thousands separators and two decimals, in the company currency."""
	currency = currency or frappe.db.get_default("currency")
	return fmt_money(flt(value), precision=2, currency=currency)  # sp-allow-number: money decimals


def ar_date(value) -> str:
	"""A date with the Arabic month name, e.g. "14 نوفمبر 2026"; empty for no value."""
	if not value:
		return ""
	d = getdate(value)
	return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def signature_block(*labels) -> Markup:
	"""Signature boxes side by side, one per label (default: the receiver and the company)."""
	labels = labels or (_("Received by"), _("For Smart Power"))
	cells = "".join(
		f'<td class="sp-signature"><div class="sp-signature-label">{escape(label)}</div>'
		f'<div class="sp-signature-line"></div></td>'
		for label in labels
	)
	return Markup(f'<table class="sp-signatures"><tr>{cells}</tr></table>')


def qr(value: str, size_px: int | None = None) -> Markup:
	"""A QR code image for a short text or link (e.g. a receipt's verification URL)."""
	from frappe.utils.print_format_generator import get_qr_code

	if not value:
		return Markup("")
	style = f' style="width:{cint(size_px)}px;height:{cint(size_px)}px"' if size_px else ""
	return Markup(f'<img class="sp-qr" alt="QR" src="{get_qr_code(str(value))}"{style}>')


# --- the base template's styles and images ------------------------------------------------------

FONT_FILES = (
	("400", "ibm-plex-sans-arabic-arabic-400-normal.woff2"),
	("400", "ibm-plex-sans-arabic-latin-400-normal.woff2"),
	("600", "ibm-plex-sans-arabic-arabic-600-normal.woff2"),
	("700", "ibm-plex-sans-arabic-arabic-700-normal.woff2"),
	("700", "ibm-plex-sans-arabic-latin-700-normal.woff2"),
)
IMAGE_TYPES = {
	".png": "image/png",
	".jpg": "image/jpeg",
	".jpeg": "image/jpeg",
	".svg": "image/svg+xml",
	".webp": "image/webp",
}


def _app_file_base64(*parts: str) -> str | None:
	"""A file of this app's public folder, as base64 (never outside that folder)."""
	import os

	public = os.path.realpath(frappe.get_app_path("smart_power", "public"))
	path = os.path.realpath(os.path.join(public, *parts))
	if not path.startswith(public + os.sep):
		return None
	return frappe.read_file(path, as_base64=True)


@functools.cache
def _styles() -> str:
	"""The print CSS with IBM Plex Sans Arabic embedded, so a PDF never depends on the network."""
	fonts = "".join(
		"@font-face{font-family:'IBM Plex Sans Arabic';font-style:normal;"
		f"font-weight:{weight};src:url(data:font/woff2;base64,{_app_file_base64('fonts', name)}) format('woff2');}}"
		for weight, name in FONT_FILES
	)
	return fonts + frappe.read_file(frappe.get_app_path("smart_power", "public", "css", "sp_print.css"))


def sp_print_styles() -> Markup:
	"""The <style> block of the base template (fonts embedded)."""
	return Markup(f"<style>{_styles()}</style>")


def embed_image(url: str | None) -> str:
	"""An app image or a site file as a data URI (header and footer pages load nothing); other
	URLs are returned as they are. Site files are read through their File record."""
	import os

	if not url:
		return ""
	mime = IMAGE_TYPES.get(os.path.splitext(url.split("?")[0])[1].lower())
	if not mime:
		return url
	content = None
	if url.startswith("/assets/smart_power/"):
		content = _app_file_base64(*url.removeprefix("/assets/smart_power/").split("/"))
	elif url.startswith(("/files/", "/private/files/")):
		name = frappe.db.get_value("File", {"file_url": url})
		if name:
			import base64

			content = base64.b64encode(frappe.get_doc("File", name).get_content(encodings=[])).decode()
	return f"data:{mime};base64,{content}" if content else url
