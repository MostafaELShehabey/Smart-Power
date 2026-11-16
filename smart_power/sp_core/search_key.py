"""One spelling for search (SP-41): Arabic written several ways matches the same text.

"احمد" finds "أحمد": the forms of alef, the taa marbuta, the alef maqsura and the hamza seats
become one letter, tatweel and diacritics go, letters are lower-cased and spaces made single.
Customer and Item keep the result in `sp_search_key`, computed on save, so a search can use it.
"""

import re

# one letter for each set of written forms (the letters are meant)
LETTERS = str.maketrans(
	{
		"أ": "ا",  # noqa: RUF001
		"إ": "ا",  # noqa: RUF001
		"آ": "ا",  # noqa: RUF001
		"ٱ": "ا",  # noqa: RUF001
		"ة": "ه",  # noqa: RUF001
		"ى": "ي",
		"ؤ": "و",
		"ئ": "ي",
		"ـ": "",  # tatweel
	}
)
DIACRITICS = re.compile("[ً-ْٰ]")  # harakat, tanween, shadda, sukun, dagger alef


def normalize(text: str | None) -> str:
	"""The searchable form of a text."""
	text = DIACRITICS.sub("", (text or "").translate(LETTERS))
	return re.sub(r"\s+", " ", text).strip().casefold()


def key_of(*parts) -> str:
	"""A record's search key: its searchable texts, normalised, in one line."""
	return " | ".join(normalize(str(p)) for p in parts if p)


def set_customer_key(doc, method=None) -> None:
	"""Customer validate: its name, mobiles and code in one searchable line."""
	doc.sp_search_key = key_of(doc.customer_name, doc.get("sp_mobile"), doc.get("sp_mobile_2"), doc.name)


def set_item_key(doc, method=None) -> None:
	"""Item validate: its code, name and Arabic name in one searchable line."""
	doc.sp_search_key = key_of(doc.item_code, doc.item_name, doc.get("sp_name_ar"), doc.get("sp_model"))
