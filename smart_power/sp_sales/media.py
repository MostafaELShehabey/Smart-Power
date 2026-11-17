"""MK3 media library (SP-53): finished-station photos and videos that installations tagged usable
for marketing, for مها to post without asking on WhatsApp.

- Only files tagged `sp_usable_for_marketing` on a station or on one of its site logs show, and
  never those of a cancelled station.
- Filters: system type, region, kW (from / to).
- No customer data leaves here: a photo carries the station no., its region, its systems and kW,
  never the customer's name or mobile, nor the file's own name or path (a photo is often named
  after the customer). The files are served by `file`, which checks the role and the tag on every
  request, so the library works although marketing cannot open the station itself.
- "Ask for more photos" gives the station's execution owner (or each installation manager when
  the station has none) a "Photo Request" task; it closes when a new photo of the station is tagged.
"""

import os

import frappe
from frappe import _
from frappe.utils import cint, flt

from smart_power.sp_core.inbox import close_tasks, create_task

LIBRARY_ROLES = ("SP Marketing Agent", "SP Admin", "System Manager")
INSTALLATION_MANAGER_ROLE = "SP Installation Manager"
PHOTO_REQUEST_TASK = "Photo Request"
STATION, LOG = "SP Station", "SP Site Daily Log"
CANCELLED = "Cancelled"
VIDEO_TYPES = (".mp4", ".mov")
MEDIA_TYPES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", *VIDEO_TYPES)
MEDIA_PATTERN = r"\.(" + "|".join(t.lstrip(".") for t in MEDIA_TYPES) + ")$"
PAGE_LENGTH = 60  # sp-allow-number: photos per page, not a business value


def _check() -> None:
	if not set(frappe.get_roles()) & set(LIBRARY_ROLES):
		frappe.throw(_("Only marketing opens the media library."), frappe.PermissionError)


def _label(name: str | None, labels: dict) -> str | None:
	return labels.get(name, name) if name else None


def _labels(list_name: str) -> dict:
	"""{value name: its label in the user's language}, for the active values of a list."""
	arabic = (frappe.local.lang or "").startswith("ar")
	rows = frappe.get_all(
		"SP List Value",
		{"list_name": list_name, "is_active": 1},
		["name", "value_ar", "value_en"],
		order_by="sort_order asc",
	)
	return {r.name: (r.value_ar if arabic else r.value_en) or r.value_ar or r.name for r in rows}


@frappe.whitelist()
def filters() -> dict:
	"""The choices of the library's filters: system types and regions."""
	_check()
	return {
		"system_types": [{"value": k, "label": v} for k, v in _labels("System Type").items()],
		"regions": [{"value": k, "label": v} for k, v in _labels("Region").items()],
	}


def _rows(
	system_type: str | None = None,
	region: str | None = None,
	kw_from=None,
	kw_to=None,
	file: str | None = None,
	start: int = 0,
	page_length: int = PAGE_LENGTH,
) -> tuple[list[dict], int]:
	"""The tagged files with their station, newest first, and how many match in all."""
	conditions = [
		"f.sp_usable_for_marketing = 1",
		"f.is_folder = 0",
		"lower(f.file_name) regexp %(media)s",
		"st.status != %(cancelled)s",
	]
	values = {"cancelled": CANCELLED, "station": STATION, "log": LOG, "media": MEDIA_PATTERN}
	if file:
		conditions.append("f.name = %(file)s")
		values["file"] = file
	if region:
		conditions.append("st.region = %(region)s")
		values["region"] = region
	if kw_from not in (None, ""):
		conditions.append("st.capacity_kw_total >= %(kw_from)s")
		values["kw_from"] = flt(kw_from)
	if kw_to not in (None, ""):
		conditions.append("st.capacity_kw_total <= %(kw_to)s")
		values["kw_to"] = flt(kw_to)
	if system_type:
		conditions.append(
			"exists (select 1 from `tabSP Station System` sys where sys.parent = st.name"
			" and sys.parenttype = %(station)s and sys.system_type = %(system_type)s)"
		)
		values["system_type"] = system_type
	# a photo is on the station itself, or on one of its site logs
	source = """from `tabFile` f
		left join `tabSP Site Daily Log` log
			on f.attached_to_doctype = %(log)s and log.name = f.attached_to_name
		join `tabSP Station` st on st.name = (
			case when f.attached_to_doctype = %(station)s then f.attached_to_name else log.station end)
		where (f.attached_to_doctype = %(station)s or log.name is not null) and """ + " and ".join(conditions)
	count_query = "select count(*) " + source
	page_query = (
		"select f.name as file, f.file_name, f.creation, st.name as station, st.region,"
		" st.capacity_kw_total as kw "
		+ source
		+ " order by f.creation desc, f.name limit %(start)s, %(page_length)s"
	)
	total = frappe.db.sql(count_query, values)[0][0]
	values.update({"start": cint(start), "page_length": cint(page_length) or PAGE_LENGTH})
	rows = frappe.db.sql(page_query, values, as_dict=True)
	return rows, total


@frappe.whitelist()
def library(
	system_type: str | None = None,
	region: str | None = None,
	kw_from: float | None = None,
	kw_to: float | None = None,
	start: int = 0,
) -> dict:
	"""A page of the library: {"photos": [...], "total": n}. Safe fields only (see the module)."""
	_check()
	rows, total = _rows(system_type, region, kw_from, kw_to, start=start)
	regions, types = _labels("Region"), _labels("System Type")
	systems = {}
	stations = list({r.station for r in rows})
	for s in frappe.get_all(
		"SP Station System",
		{"parent": ("in", stations or [""]), "parenttype": STATION},
		["parent", "system_type"],
		order_by="idx asc",
	):
		label = _label(s.system_type, types)
		if label and label not in systems.setdefault(s.parent, []):
			systems[s.parent].append(label)
	photos = []
	for r in rows:
		ext = os.path.splitext(r.file_name or "")[1].lower()
		photos.append(
			{
				"file": r.file,
				"station": r.station,
				"region": _label(r.region, regions),
				"systems": systems.get(r.station, []),
				"kw": flt(r.kw),
				"date": str(r.creation.date()),
				"video": ext in VIDEO_TYPES,
			}
		)
	return {"photos": photos, "total": total}


@frappe.whitelist(methods=["GET"])
def file(name: str, download: int = 0) -> None:
	"""The content of a tagged photo, shown in the grid or downloaded as <station>-<file no.>."""
	_check()
	rows, _total = _rows(file=name, page_length=1)
	if not rows:
		frappe.throw(_("This file is not in the media library."), frappe.PermissionError)
	row = rows[0]
	ext = os.path.splitext(row.file_name or "")[1].lower()
	frappe.local.response.filename = f"{row.station}-{row.file}{ext}"
	frappe.local.response.filecontent = frappe.get_doc("File", name).get_content()
	frappe.local.response.type = "download"
	frappe.local.response.display_content_as = "attachment" if cint(download) else "inline"


@frappe.whitelist(methods=["POST"])
def request_photos(station: str, note: str | None = None) -> int:
	"""Ask installations for more photos of a station; returns how many were asked (0 when the
	request is already open)."""
	_check()
	status, owner = frappe.db.get_value(STATION, station, ["status", "execution_owner"]) or (None, None)
	if not status:
		frappe.throw(_("Station {0} not found.").format(station), frappe.DoesNotExistError)
	if status == CANCELLED:
		frappe.throw(_("Station {0} is cancelled.").format(station))
	users = [owner] if owner and frappe.db.get_value("User", owner, "enabled") else _installation_managers()
	if not users:
		frappe.throw(_("No installation manager to ask."))
	return len(
		create_task(
			PHOTO_REQUEST_TASK,
			STATION,
			station,
			users,
			_("More photos of station {0} for marketing").format(station),
			description=note,
		)
	)


def _installation_managers() -> list[str]:
	users = frappe.get_all(
		"Has Role", {"role": INSTALLATION_MANAGER_ROLE, "parenttype": "User"}, pluck="parent"
	)
	return frappe.get_all("User", {"name": ("in", users or [""]), "enabled": 1}, pluck="name")


def photo_tagged(doctype: str, name: str) -> None:
	"""A photo of a station (or of its site log) was tagged usable: its photo requests are done."""
	station = name if doctype == STATION else frappe.db.get_value(LOG, name, "station")
	if station:
		close_tasks(STATION, station, PHOTO_REQUEST_TASK)
