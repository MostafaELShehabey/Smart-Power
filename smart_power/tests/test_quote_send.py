"""Sending a quote version (SP-61)."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_datetime, now_datetime

from smart_power.sp_core.documents import seed_quote_template
from smart_power.sp_quotes.quote_send import send_options, send_quote
from smart_power.tests.utils import load_erpnext_test_data, make_quotation, make_user, set_setting

load_erpnext_test_data()

LOG = "SP Quote Send Log"


def blank_pdf() -> bytes:
	import io

	from pypdf import PdfWriter

	writer = PdfWriter()
	writer.add_blank_page(width=72, height=72)
	stream = io.BytesIO()
	writer.write(stream)
	return stream.getvalue()


class TestQuoteSend(IntegrationTestCase):
	def setUp(self):
		# CI skips building assets; printing looks bundles up in assets.json
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)
		seed_quote_template()
		set_setting(followup_delay_days=2, default_quote_print_format="SP Quotation")
		self.quote = make_quotation()
		self.case = frappe.get_doc("SP Case", self.quote.sp_case)

	def send(self, name=None, **kw):
		# CI has no Chromium: the PDF itself is SP-62's; here a stand-in PDF is enough
		with patch("frappe.get_print", return_value=blank_pdf()):
			return send_quote(name or self.quote.name, **kw)

	def test_first_send_freezes_the_version_and_moves_the_case(self):
		result = self.send()
		quote = frappe.get_doc("Quotation", self.quote.name)
		self.assertEqual(quote.docstatus, 1)
		self.assertEqual(quote.sp_status, "Sent")
		case = frappe.get_doc("SP Case", self.case.name)
		self.assertEqual(case.status, "Sent to customer")
		self.assertTrue(case.quote_sent_at)  # the 24 h clock stops
		log = frappe.get_doc(LOG, result["log"])
		self.assertEqual(
			(log.quotation, log.case, log.channel, log.print_format, log.sent_by),
			(quote.name, case.name, "WhatsApp", "SP Quotation", "Administrator"),
		)
		self.assertTrue(frappe.db.get_value("File", log.file, "is_private"))

	def test_sent_twice_gives_two_logs_with_their_own_pdf_and_no_edit(self):
		self.send()
		self.send()
		logs = frappe.get_all(LOG, {"quotation": self.quote.name}, ["file", "file_url"])
		self.assertEqual(len(logs), 2)
		self.assertNotEqual(logs[0].file, logs[1].file)
		quote = frappe.get_doc("Quotation", self.quote.name)
		quote.items[0].qty = 99
		with self.assertRaises(frappe.ValidationError):
			quote.save()

	def test_follow_up_owner_gets_a_call_task_after_the_delay(self):
		self.send()
		task = frappe.get_all(
			"SP Task",
			{"reference_name": self.case.name, "task_type": "Follow-up Call", "status": "Open"},
			["assigned_to", "due_at"],
		)
		self.assertEqual(len(task), 1)
		self.assertEqual(task[0].assigned_to, self.case.follow_up_owner)
		days = (get_datetime(task[0].due_at) - now_datetime()).total_seconds() / 86400
		self.assertAlmostEqual(days, 2, delta=0.1)
		self.send()  # a second send does not add a second open call task
		self.assertEqual(
			frappe.db.count(
				"SP Task", {"reference_name": self.case.name, "task_type": "Follow-up Call", "status": "Open"}
			),
			1,
		)

	def test_requester_and_follow_up_owner_are_told(self):
		# real users: Frappe finds recipients by email, and Administrator's is admin@example.com
		requester = make_user("sp.send.requester@example.com", ("lead_intake",))
		owner = make_user("sp.send.owner@example.com", ("customer_followup",))
		frappe.db.set_value("SP Case", self.case.name, {"requested_by": requester, "follow_up_owner": owner})
		self.send()
		told = set(frappe.get_all("Notification Log", {"document_name": self.case.name}, pluck="for_user"))
		self.assertTrue({requester, owner} <= told)

	def test_margin_outside_its_range_warns_and_never_blocks(self):
		self.case.append("system_types", {"system_type": "System Type-PUMP"})
		self.case.save()
		set_setting(margin_ranges=[{"offer_type": "System Type-PUMP", "min_pct": 90, "max_pct": 95}])
		result = self.send()
		self.assertEqual(len(result["warnings"]), 1)
		self.assertEqual(frappe.db.get_value("Quotation", self.quote.name, "docstatus"), 1)
		self.assertTrue(
			frappe.db.exists("SP Review Item", {"reference_name": self.quote.name, "status": "Open"})
		)

	def test_only_the_cases_people(self):
		other = make_user("sp.send.other@example.com", ("customer_followup",))
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				self.send()
		finally:
			frappe.set_user("Administrator")

	def test_bad_channel_or_format_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.send(channel="Fax")
		with self.assertRaises(frappe.ValidationError):
			self.send(print_format="SP Print Sample")

	def test_a_lost_case_sends_nothing(self):
		frappe.db.set_value("SP Case", self.case.name, "status", "Lost")
		with self.assertRaises(frappe.ValidationError):
			self.send()

	def test_send_dialog_options(self):
		options = send_options(self.quote.name)
		self.assertEqual(options["default"], "SP Quotation")
		self.assertIn("SP Quotation", options["formats"])
		self.assertEqual(options["channels"], ["WhatsApp", "In person", "Other"])

	def test_update_items_cannot_change_a_sent_version(self):
		# found in the browser check: ERPNext's "Update Items" edits a submitted quote's lines
		import json

		from smart_power.sp_sales.quotation import update_child_qty_rate  # what the button reaches

		self.send()
		row = frappe.get_doc("Quotation", self.quote.name).items[0]
		trans = [
			{
				"docname": row.name,
				"item_code": row.item_code,
				"qty": 99,
				"rate": row.rate,
				"conversion_factor": 1,
			}
		]
		with self.assertRaises(frappe.ValidationError):
			update_child_qty_rate("Quotation", json.dumps(trans), self.quote.name)
		self.assertEqual(frappe.db.get_value("Quotation Item", row.name, "qty"), row.qty)
		self.assertEqual(
			frappe.get_hooks("override_whitelisted_methods")[
				"erpnext.controllers.accounts_controller.update_child_qty_rate"
			][-1],
			"smart_power.sp_sales.quotation.update_child_qty_rate",
		)
