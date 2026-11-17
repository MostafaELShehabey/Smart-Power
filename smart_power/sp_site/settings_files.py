"""SET1 settings library (SP-98): inverter parameter files per brand and model, with versions.

- Each upload of a brand + model is its next version (v1, v2 ...), with notes on what changed.
  The newest is the "latest"; older versions stay and can still be downloaded.
- Deleting the latest version (admin) makes the one before it the latest again.
- `latest(brand, model)` is what programming and commissioning (PR1, SP-97) suggests.
- `import_folder(path)` loads today's SETTING folder (<brand>/<model>/<file>), oldest file
  first, for the go-live migration (E17): run it with `bench execute`.

The files are private: whoever may read the settings library may download them.
"""

import os

import frappe
from frappe import _
from frappe.core.doctype.file.utils import get_content_hash
from frappe.utils import cint, get_datetime

SETTINGS_FILE = "SP Settings File"
LIST_VALUE = "SP List Value"
BRAND_LIST = "Inverter Brand"


def _brand_label(brand: str | None) -> str:
	if not brand:
		return ""
	value_en, code = frappe.db.get_value(LIST_VALUE, brand, ["value_en", "code"]) or (None, None)
	return value_en or code or brand


def _last_version(brand: str, model: str) -> int:
	last = frappe.get_all(
		SETTINGS_FILE, {"brand": brand, "model": model}, pluck="version", order_by="version desc", limit=1
	)
	return cint(last[0]) if last else 0


def before_insert(doc) -> None:
	doc.model = (doc.model or "").strip()
	doc.version = _last_version(doc.brand, doc.model) + 1
	doc.is_latest = 1
	doc.uploaded_by = frappe.session.user


def validate(doc) -> None:
	doc.model = (doc.model or "").strip()
	_keep_private(doc)
	if frappe.db.get_value(LIST_VALUE, doc.brand, "list_name") != BRAND_LIST:
		frappe.throw(_("{0} is not an inverter brand.").format(frappe.bold(doc.brand)))
	doc.title = f"{_brand_label(doc.brand)} {doc.model} v{doc.version}"


def _keep_private(doc) -> None:
	"""A settings file uploaded as public is made private (only the library's readers download it)."""
	if not (doc.file or "").startswith("/files/"):
		return
	name = frappe.db.get_value(
		"File",
		{"file_url": doc.file, "owner": frappe.session.user, "attached_to_name": ("is", "not set")},
		"name",
	)
	if name:
		file_doc = frappe.get_doc("File", name)
		file_doc.is_private = 1
		file_doc.save(ignore_permissions=True)
		doc.file = file_doc.file_url


def after_insert(doc) -> None:
	"""The new version is the latest; the previous one stays, no longer latest."""
	for name in frappe.get_all(
		SETTINGS_FILE,
		{"brand": doc.brand, "model": doc.model, "is_latest": 1, "name": ("!=", doc.name)},
		pluck="name",
	):
		frappe.db.set_value(SETTINGS_FILE, name, "is_latest", 0, update_modified=False)


def on_trash(doc) -> None:
	if not doc.is_latest:
		return
	previous = frappe.get_all(
		SETTINGS_FILE,
		{"brand": doc.brand, "model": doc.model, "name": ("!=", doc.name)},
		pluck="name",
		order_by="version desc",
		limit=1,
	)
	if previous:
		frappe.db.set_value(SETTINGS_FILE, previous[0], "is_latest", 1, update_modified=False)


# --- the library ------------------------------------------------------------------------------

FIELDS = [
	"name",
	"title",
	"brand",
	"model",
	"version",
	"file",
	"notes",
	"uploaded_by",
	"creation",
	"is_latest",
]


def _row(r) -> dict:
	return {**r, "brand_label": _brand_label(r.brand), "creation": str(get_datetime(r.creation).date())}


@frappe.whitelist()
def latest(brand: str, model: str) -> dict | None:
	"""The latest file of a brand and model (what PR1 suggests), or None."""
	frappe.has_permission(SETTINGS_FILE, "read", throw=True)
	rows = frappe.get_all(
		SETTINGS_FILE, {"brand": brand, "model": (model or "").strip(), "is_latest": 1}, FIELDS, limit=1
	)
	return _row(rows[0]) if rows else None


@frappe.whitelist()
def library(brand: str | None = None, search: str | None = None) -> list[dict]:
	"""The latest version of every brand and model, with how many versions each has."""
	frappe.has_permission(SETTINGS_FILE, "read", throw=True)
	filters = {"is_latest": 1}
	if brand:
		filters["brand"] = brand
	or_filters = None
	if search:
		like = f"%{search.strip()}%"
		or_filters = {"model": ("like", like), "title": ("like", like), "notes": ("like", like)}
	rows = frappe.get_all(
		SETTINGS_FILE, filters, FIELDS, or_filters=or_filters, order_by="brand asc, model asc"
	)
	counts = {
		(r.brand, r.model): r.n
		for r in frappe.get_all(
			SETTINGS_FILE,
			fields=["brand", "model", {"COUNT": "*", "as": "n"}],
			group_by="brand, model",
		)
	}
	return [{**_row(r), "versions": counts.get((r.brand, r.model), 1)} for r in rows]


@frappe.whitelist()
def history(brand: str, model: str) -> list[dict]:
	"""Every version of a brand and model, newest first."""
	frappe.has_permission(SETTINGS_FILE, "read", throw=True)
	return [
		_row(r)
		for r in frappe.get_all(
			SETTINGS_FILE, {"brand": brand, "model": model}, FIELDS, order_by="version desc"
		)
	]


@frappe.whitelist(methods=["POST"])
def upload(brand: str, model: str, file_url: str, notes: str | None = None) -> dict:
	"""Upload a file as the next version of a brand and model; returns the new version."""
	doc = frappe.get_doc(
		{"doctype": SETTINGS_FILE, "brand": brand, "model": model, "file": file_url, "notes": notes}
	).insert()
	return _row(frappe._dict({f: doc.get(f) for f in FIELDS}))


# --- migration: today's SETTING folder (E17) ----------------------------------------------------


def _brand(folder: str) -> str:
	"""The Inverter Brand value for a folder name, made when it is new."""
	key = folder.strip()
	for r in frappe.get_all(LIST_VALUE, {"list_name": BRAND_LIST}, ["name", "code", "value_en", "value_ar"]):
		if key.lower() in {(v or "").strip().lower() for v in (r.code, r.value_en, r.value_ar)}:
			return r.name
	return (
		frappe.get_doc(
			{
				"doctype": LIST_VALUE,
				"list_name": BRAND_LIST,
				"code": "".join(c if c.isalnum() else "_" for c in key.upper()),
				"value_ar": key,
				"value_en": key,
				"is_active": 1,
			}
		)
		.insert()
		.name
	)


def import_folder(path: str, notes: str | None = None) -> dict:
	"""Load <path>/<brand>/<model>/<file> into the library, each model's files oldest first as
	v1, v2 ...; a file already in the library (same content for that model) is skipped.
	Returns {"added": n, "skipped": n}. Run with: bench --site <site> execute
	smart_power.sp_site.settings_files.import_folder --kwargs "{'path': '/path/to/SETTING'}"
	"""
	frappe.only_for(("System Manager", "SP Admin"))
	added = skipped = 0
	for brand_dir in sorted(os.listdir(path)):
		brand_path = os.path.join(path, brand_dir)
		if not os.path.isdir(brand_path):
			continue
		brand = _brand(brand_dir)
		for model in sorted(os.listdir(brand_path)):
			model_path = os.path.join(brand_path, model)
			if not os.path.isdir(model_path):
				continue
			files = [
				os.path.join(model_path, f)
				for f in os.listdir(model_path)
				if os.path.isfile(os.path.join(model_path, f))
			]
			known = _known_hashes(brand, model.strip())
			for file_path in sorted(files, key=lambda p: (os.path.getmtime(p), p)):
				# admin-only, run from bench on a folder of the server (never whitelisted)
				with open(file_path, "rb") as f:  # nosemgrep
					content = f.read()
				if get_content_hash(content) in known:
					skipped += 1
					continue
				file_doc = frappe.get_doc(
					{
						"doctype": "File",
						"file_name": os.path.basename(file_path),
						"content": content,
						"is_private": 1,
					}
				).insert()
				frappe.get_doc(
					{
						"doctype": SETTINGS_FILE,
						"brand": brand,
						"model": model,
						"file": file_doc.file_url,
						"notes": notes or _("Imported from the SETTING folder"),
					}
				).insert()
				added += 1
	return {"added": added, "skipped": skipped}


def _known_hashes(brand: str, model: str) -> set[str]:
	urls = frappe.get_all(SETTINGS_FILE, {"brand": brand, "model": model}, pluck="file")
	return set(frappe.get_all("File", {"file_url": ("in", urls or [""])}, pluck="content_hash"))
