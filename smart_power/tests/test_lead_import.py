"""Import leads (SP-51, C3b): dry-run counts, duplicates, the background import, the result file."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from smart_power.sp_sales import lead_import
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()


def mobile(n: int) -> str:
	return f"0100560{n:04d}"


def upload(user: str, rows: list[list], name="leads.csv") -> str:
	text = "\n".join(",".join(str(c) for c in r) for r in rows)
	frappe.set_user(user)
	try:
		return (
			frappe.get_doc(
				{"doctype": "File", "file_name": name, "content": text.encode("utf-8"), "is_private": 1}
			)
			.insert()
			.file_url
		)
	finally:
		frappe.set_user("Administrator")


def as_user(user, fn, *args, **kw):
	frappe.set_user(user)
	try:
		return fn(*args, **kw)
	finally:
		frappe.set_user("Administrator")


class TestLeadImport(IntegrationTestCase):
	def setUp(self):
		self.maha = make_user("sp.li.maha@example.com", ("marketing_agent", "lead_intake", "quote_creator"))
		self.campaign = (
			frappe.get_doc(
				{
					"doctype": "SP Campaign",
					"campaign_name": "معرض صحارى",
					"channel": "Lead Source-EXHIBITION",
					"start_date": today(),
					"owner_user": self.maha,
				}
			)
			.insert()
			.name
		)

	def test_200_rows_with_15_existing_mobiles(self):
		for n in range(15):  # 15 mobiles already leads
			frappe.get_doc({"doctype": "Lead", "lead_name": f"قديم {n}", "sp_mobile": mobile(n)}).insert()
		rows = [["الاسم", "الموبايل", "المدينة"]] + [[f"زائر {n}", mobile(n), "الخارجة"] for n in range(200)]
		url = upload(self.maha, rows)
		cols = as_user(self.maha, lead_import.read_columns, url)
		self.assertEqual(cols["mapping"], {"lead_name": 0, "sp_mobile": 1, "city": 2})  # guessed from Arabic
		result = as_user(self.maha, lead_import.dry_run, url, cols["mapping"], self.campaign)
		self.assertEqual((result["new"], result["duplicate_count"], result["error_count"]), (185, 15, 0))
		name = as_user(self.maha, lead_import.start, url, cols["mapping"], self.campaign)
		doc = frappe.get_doc("SP Lead Import", name)
		self.assertEqual((doc.status, doc.new_count, doc.duplicate_count), ("Done", 185, 15))
		self.assertTrue(doc.result_file)
		made = frappe.get_all("Lead", {"sp_campaign": self.campaign}, ["owner", "lead_owner"])
		self.assertEqual(len(made), 185)
		self.assertEqual({(m.owner, m.lead_owner) for m in made}, {(self.maha, self.maha)})
		self.assertEqual(frappe.db.get_value("SP Campaign", self.campaign, "lead_count"), 185)

	def test_errors_and_repeats_in_the_file(self):
		rows = [
			["Name", "Mobile"],
			["أحمد", mobile(300)],
			["", mobile(301)],
			["علي", "123"],
			["أحمد مكرر", mobile(300)],
		]
		url = upload(self.maha, rows)
		result = as_user(self.maha, lead_import.dry_run, url, {"lead_name": 0, "sp_mobile": 1})
		self.assertEqual((result["new"], result["duplicate_count"], result["error_count"]), (1, 1, 2))
		self.assertEqual(result["duplicates"][0]["row"], 5)  # spreadsheet row of the repeat

	def test_name_and_mobile_columns_are_required(self):
		url = upload(self.maha, [["Name", "Mobile"], ["أحمد", mobile(310)]])
		with self.assertRaises(frappe.ValidationError):
			as_user(self.maha, lead_import.dry_run, url, {"lead_name": 0})

	def test_only_who_may_make_leads(self):
		nobody = make_user("sp.li.nobody@example.com", ("main_store_keeper",))
		url = upload(self.maha, [["Name", "Mobile"], ["أحمد", mobile(320)]])
		with self.assertRaises(frappe.PermissionError):
			as_user(nobody, lead_import.dry_run, url, {"lead_name": 0, "sp_mobile": 1})
