"""MK3 media library (SP-53): only photos tagged usable for marketing, filtered by system, region
and kW, with no customer data; "ask for more photos" gives installations a task."""

import io
import json
import os

import frappe
from frappe.tests import IntegrationTestCase
from PIL import Image

from smart_power.sp_core.inbox import OPEN
from smart_power.sp_sales import media
from smart_power.sp_site import site_log
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"
ONGRID, PUMP = "System Type-ONGRID", "System Type-PUMP"
SAFE_FIELDS = {"file", "station", "region", "systems", "kw", "date", "video"}


def png() -> bytes:
	out = io.BytesIO()
	Image.new("RGB", (4, 4), "gold").save(out, format="PNG")
	return out.getvalue()


class TestMediaLibrary(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.disk = set()

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		# the rollback drops the File rows; the content they wrote stays on disk
		for path in cls.disk:
			if os.path.exists(path):
				os.remove(path)

	def setUp(self):
		self.kharga = self.region("KHARGA", "الخارجة", "Kharga")
		self.dakhla = self.region("DAKHLA", "الداخلة", "Dakhla")
		self.a = self.station(self.kharga, ONGRID, 10)  # 12 tagged: 10 on it, 2 on its site log
		self.b = self.station(self.kharga, PUMP, 0)  # 10 tagged
		self.c = self.station(self.dakhla, ONGRID, 20)  # 8 tagged
		for n in range(10):
			self.photo("SP Station", self.a.name, f"a-{n}.png")
			self.photo("SP Station", self.b.name, f"b-{n}.png")
		log = frappe.get_doc(
			{
				"doctype": "SP Site Daily Log",
				"station": self.a.name,
				"work_date": frappe.utils.today(),
				"stages": [{"stage": "Site Stage-PANELS"}],
			}
		).insert()
		for n in range(2):
			self.photo("SP Site Daily Log", log.name, f"log-{n}.png")
		for n in range(8):
			self.photo("SP Station", self.c.name, f"c-{n}.png")
		# the same station's receipt photo, never tagged
		self.receipt = self.photo("SP Station", self.a.name, "receipt.png", usable=0)
		self.maha = make_user("sp.ml.maha@example.com", ("marketing_agent",))
		self.mostafa = make_user("sp.ml.mostafa@example.com", ("installation_manager",))

	def region(self, code, ar, en):
		name = f"Region-{code}"
		if not frappe.db.exists("SP List Value", name):
			frappe.get_doc(
				{
					"doctype": "SP List Value",
					"list_name": "Region",
					"code": code,
					"value_ar": ar,
					"value_en": en,
					"is_active": 1,
				}
			).insert()
		return name

	def station(self, region, system_type, kw):
		return frappe.get_doc(
			{
				"doctype": "SP Station",
				"customer": "_Test Customer",
				"company": COMPANY,
				"region": region,
				"systems": [{"system_type": system_type, "capacity_kw": kw, "qty": 1}],
			}
		).insert()

	def photo(self, doctype, name, file_name, usable=1):
		f = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"content": png(),
				"attached_to_doctype": doctype,
				"attached_to_name": name,
				"is_private": 1,
			}
		).insert()
		self.disk.add(f.get_full_path())
		if usable:
			frappe.db.set_value("File", f.name, "sp_usable_for_marketing", 1)
		return f

	def as_maha(self, fn, *args, **kw):
		frappe.set_user(self.maha)
		try:
			return fn(*args, **kw)
		finally:
			frappe.set_user("Administrator")

	def ours(self, result):
		"""The rows of this test's stations (the site may hold other tagged photos)."""
		mine = {self.a.name, self.b.name, self.c.name}
		return [p for p in result["photos"] if p["station"] in mine]

	def test_filter_on_grid_in_kharga(self):
		found = self.ours(self.as_maha(media.library, system_type=ONGRID, region=self.kharga))
		self.assertEqual(len(found), 12)
		self.assertEqual({p["station"] for p in found}, {self.a.name})
		self.assertEqual(len(self.ours(self.as_maha(media.library))), 30)
		by_kw = self.ours(self.as_maha(media.library, kw_from=5, kw_to=15))
		self.assertEqual({p["station"] for p in by_kw}, {self.a.name})

	def test_untagged_receipt_never_shows(self):
		files = {p["file"] for p in self.ours(self.as_maha(media.library))}
		self.assertNotIn(self.receipt.name, files)
		with self.assertRaises(frappe.PermissionError):
			self.as_maha(media.file, self.receipt.name)

	def test_no_customer_data(self):
		photos = self.ours(self.as_maha(media.library, region=self.kharga))
		self.assertTrue(photos)
		self.assertTrue(all(set(p) == SAFE_FIELDS for p in photos))
		dump = json.dumps(photos, ensure_ascii=False, default=str)
		self.assertNotIn("_Test Customer", dump)
		self.assertNotIn(".png", dump)  # nor the file's own name or path
		first = next(p for p in photos if p["station"] == self.a.name)
		self.assertEqual(first["systems"], [media._labels("System Type")[ONGRID]])
		self.assertEqual(first["kw"], 10)

	def test_download_serves_the_tagged_file(self):
		file = self.ours(self.as_maha(media.library, region=self.dakhla))[0]
		self.as_maha(media.file, file["file"], download=1)
		self.assertEqual(frappe.local.response.filename, f"{self.c.name}-{file['file']}.png")
		self.assertEqual(frappe.local.response.filecontent[:4], b"\x89PNG")
		self.assertEqual(frappe.local.response.display_content_as, "attachment")

	def test_cancelled_station_is_hidden(self):
		frappe.db.set_value("SP Station", self.c.name, "status", "Cancelled")
		self.assertEqual(len(self.ours(self.as_maha(media.library))), 22)

	def test_only_marketing_opens_it(self):
		frappe.set_user(self.mostafa)
		try:
			with self.assertRaises(frappe.PermissionError):
				media.library()
			with self.assertRaises(frappe.PermissionError):
				media.request_photos(self.a.name)
		finally:
			frappe.set_user("Administrator")

	def test_ask_for_more_photos(self):
		frappe.db.set_value("SP Station", self.a.name, "execution_owner", self.mostafa)
		self.assertEqual(self.as_maha(media.request_photos, self.a.name, "the panels from above"), 1)
		task = {
			"task_type": media.PHOTO_REQUEST_TASK,
			"reference_doctype": "SP Station",
			"reference_name": self.a.name,
			"assigned_to": self.mostafa,
		}
		self.assertEqual(frappe.db.get_value("SP Task", task, "status"), OPEN)
		self.assertEqual(self.as_maha(media.request_photos, self.a.name), 0)  # already asked
		# installations tag a new photo of the station: the request is answered
		new = self.photo("SP Station", self.a.name, "from-above.png", usable=0)
		site_log.set_marketing(new.name, 1)
		self.assertEqual(frappe.db.get_value("SP Task", task, "status"), "Done")

	def test_station_without_owner_asks_each_installation_manager(self):
		frappe.db.set_value("SP Station", self.b.name, "execution_owner", None)
		self.as_maha(media.request_photos, self.b.name)
		asked = frappe.get_all(
			"SP Task",
			{"task_type": media.PHOTO_REQUEST_TASK, "reference_name": self.b.name},
			pluck="assigned_to",
		)
		self.assertIn(self.mostafa, asked)
