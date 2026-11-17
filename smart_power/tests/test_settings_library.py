"""SET1 settings library (SP-98): versions per brand and model, the latest suggested, old ones kept."""

import os
import shutil
import tempfile

import frappe
from frappe.tests import IntegrationTestCase

from smart_power.sp_core.setup.seed import seed_list_values
from smart_power.sp_site import settings_files as sf
from smart_power.tests.utils import make_user

INVT = "Inverter Brand-INVT"


class TestSettingsLibrary(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed_list_values()
		cls.disk = set()

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		# the rollback drops the File rows; what they wrote stays on disk
		for path in cls.disk:
			if os.path.exists(path):
				os.remove(path)

	def setUp(self):
		# the class shares one transaction, so each test has its own model
		self.model = f"GD100 {self._testMethodName}"

	def file(self, name, content, private=1):
		f = frappe.get_doc(
			{"doctype": "File", "file_name": name, "content": content, "is_private": private}
		).insert()
		self.disk.add(f.get_full_path())
		return f

	def upload(self, n, notes=None):
		f = self.file(f"gd100-v{n}.par", f"P01={n}\n".encode())
		return sf.upload(INVT, self.model, f.file_url, notes)

	def test_new_version_is_latest_and_old_one_stays(self):
		self.upload(1)
		v2 = self.upload(2, "pump curve")
		v3 = self.upload(3, "dry-run protection on")
		self.assertEqual((v2["version"], v3["version"]), (2, 3))
		versions = {v["version"]: v for v in sf.history(INVT, self.model)}
		self.assertEqual([v["is_latest"] for v in sf.history(INVT, self.model)], [1, 0, 0])
		self.assertEqual(versions[3]["notes"], "dry-run protection on")
		# v2 can still be downloaded, by the field roles too
		tech = make_user("sp.set.tech@example.com", ("installation_technician",))
		frappe.set_user(tech)
		try:
			old = frappe.get_doc("File", {"file_url": versions[2]["file"]})
			self.assertTrue(frappe.has_permission("File", "read", old))
			self.assertEqual(frappe.safe_decode(old.get_content()), "P01=2\n")
		finally:
			frappe.set_user("Administrator")

	def test_latest_is_suggested(self):
		self.upload(1)
		self.upload(2)
		self.assertEqual(sf.latest(INVT, self.model)["version"], 2)
		self.assertEqual(sf.latest(INVT, f"  {self.model} ")["version"], 2)  # spaces do not matter
		self.assertIsNone(sf.latest(INVT, "no such model"))
		row = next(r for r in sf.library(brand=INVT) if r["model"] == self.model)
		self.assertEqual((row["version"], row["versions"]), (2, 2))
		self.assertEqual(row["title"], f"INVT {self.model} v2")

	def test_deleting_the_latest_brings_back_the_one_before(self):
		self.upload(1)
		v2 = self.upload(2)
		frappe.delete_doc(sf.SETTINGS_FILE, v2["name"])
		self.assertEqual(sf.latest(INVT, self.model)["version"], 1)

	def test_only_an_inverter_brand(self):
		f = self.file("x.par", b"P01=0\n")
		with self.assertRaises(frappe.ValidationError):
			sf.upload("System Type-PUMP", self.model, f.file_url)

	def test_a_public_upload_is_made_private(self):
		from unittest.mock import MagicMock, patch

		f = self.file("public.par", b"P01=9\n", private=0)
		# the class rollback would move the file back to public after the test's own cleanup
		with patch.object(frappe.db, "after_rollback", MagicMock()):
			v = sf.upload(INVT, self.model, f.file_url)
		self.assertTrue(v["file"].startswith("/private/files/"))
		self.disk.add(frappe.get_doc("File", {"file_url": v["file"]}).get_full_path())

	def test_field_technician_reads_but_does_not_upload(self):
		tech = make_user("sp.set.tech@example.com", ("installation_technician",))
		f = self.file("t.par", b"P01=1\n")
		frappe.set_user(tech)
		try:
			with self.assertRaises(frappe.PermissionError):
				sf.upload(INVT, self.model, f.file_url)
			sf.library()
		finally:
			frappe.set_user("Administrator")

	def test_import_the_setting_folder(self):
		root = tempfile.mkdtemp()
		self.addCleanup(shutil.rmtree, root)
		for brand, model, name, content, mtime in (
			("INVT", self.model, "old.par", b"P01=1\n", 1_000),
			("INVT", self.model, "new.par", b"P01=2\n", 2_000),
			("Acme Drives", "AX-7", "ax7.par", b"P01=7\n", 1_000),
		):
			folder = os.path.join(root, brand, model)
			os.makedirs(folder, exist_ok=True)
			path = os.path.join(folder, name)
			with open(path, "wb") as out:
				out.write(content)
			os.utime(path, (mtime, mtime))
		self.assertEqual(sf.import_folder(root), {"added": 3, "skipped": 0})
		for v in sf.history(INVT, self.model):
			self.disk.add(frappe.get_doc("File", {"file_url": v["file"]}).get_full_path())
		acme = frappe.db.get_value(
			"SP List Value", {"list_name": "Inverter Brand", "value_en": "Acme Drives"}
		)
		self.assertTrue(acme)
		for v in sf.history(acme, "AX-7"):
			self.disk.add(frappe.get_doc("File", {"file_url": v["file"]}).get_full_path())
		# the oldest file is v1, the newest the latest
		latest = sf.latest(INVT, self.model)
		self.assertEqual(latest["version"], 2)
		self.assertEqual(
			frappe.safe_decode(frappe.get_doc("File", {"file_url": latest["file"]}).get_content()), "P01=2\n"
		)
		# a second run adds nothing
		self.assertEqual(sf.import_folder(root), {"added": 0, "skipped": 3})
