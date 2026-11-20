"""Consignment reconciliation (SP-93): our container figures against the supplier's monthly statement."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, get_first_day, get_last_day, nowdate

from smart_power.sp_stock import consignment
from smart_power.sp_stock import consignment_reconciliation as cr
from smart_power.tests.test_consignment import COMPANY, ITEM, SUPPLIER, ensure_supplier
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

STATEMENT = "/private/files/sp93-statement.pdf"


class TestConsignmentReconciliation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_supplier()
		cls.keeper = make_user("sp.crc.keeper@example.com", ("main_store_keeper",))
		cls.admin = make_user("sp.crc.admin@example.com", ("admin",))
		cls.other = make_user("sp.crc.other@example.com", ("site_receiver",))
		cls.month = get_first_day(add_months(nowdate(), -1))
		cls.month_end = get_last_day(cls.month)
		# MSKU123: 40 pallets of 33 = 1,320 panels; 96 handed over last month leaves 1,224
		cls.msku = cls.container("MSKU123", 40, cls.month)
		consignment.make_movement(
			cls.msku.name,
			consignment.HAND_OVER,
			96,
			customer_name="عميل التجربة",
			movement_date=add_days(cls.month, 9),
		)
		# after the month: never in last month's figures
		consignment.make_movement(cls.msku.name, consignment.RETURN, 33, movement_date=nowdate())

	@classmethod
	def container(cls, number, pallets, received_on):
		return frappe.get_doc(
			{
				"doctype": consignment.CONTAINER,
				"supplier": SUPPLIER,
				"item": ITEM,
				"company": COMPANY,
				"container_no": number,
				"pallets": pallets,
				"per_pallet": 33,
				"received_on": received_on,
			}
		).insert()

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete(cr.RECONCILIATION, {"supplier": SUPPLIER})

	def as_user(self, user, action, *args, **kwargs):
		frappe.set_user(user)
		try:
			return action(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def sheet(self):
		made = cr.create_monthly()
		name = frappe.db.get_value(cr.RECONCILIATION, {"supplier": SUPPLIER, "period": self.month})
		self.assertIn(name, made)
		return frappe.get_doc(cr.RECONCILIATION, name)

	def type_statement(self, doc, number, **figures):
		"""The keeper types the supplier's statement for one container; the rest agree with ours."""
		frappe.set_user(self.keeper)
		try:
			doc = frappe.get_doc(cr.RECONCILIATION, doc.name)
			for line in doc.lines:
				for ours, theirs in cr.PAIRS:
					line.set(theirs, line.get(ours))
				if line.container_no == number:
					line.update(figures)
			doc.statement_file = STATEMENT
			doc.save()
			return doc
		finally:
			frappe.set_user("Administrator")

	def line(self, doc, number):
		return next(l for l in frappe.get_doc(cr.RECONCILIATION, doc.name).lines if l.container_no == number)

	def test_our_1224_against_their_1200_is_minus_24_and_tells_the_admin(self):
		doc = self.sheet()
		self.assertTrue(
			frappe.db.exists(
				"SP Task", {"reference_name": doc.name, "task_type": cr.TASK, "assigned_to": self.keeper}
			)
		)
		ours = self.line(doc, "MSKU123")
		self.assertEqual(
			(ours.our_received, ours.our_handed_over, ours.our_returned, ours.our_remaining),
			(1320, 96, 0, 1224),
		)
		doc = self.type_statement(
			doc, "MSKU123", supplier_handed_over=120, supplier_remaining=1200, note="تسليم 24 لم يصلنا إذنه"
		)
		self.assertEqual(
			(self.line(doc, "MSKU123").diff, self.line(doc, "MSKU123").line_status), (-24, cr.LINE_DIFFERENCE)
		)
		result = self.as_user(self.keeper, cr.finish, doc.name)
		self.assertEqual(result, {"status": cr.WITH_DIFFERENCES, "differences": 1})
		self.assertTrue(
			frappe.db.exists(
				"Notification Log",
				{"for_user": self.admin, "document_type": cr.RECONCILIATION, "document_name": doc.name},
			)
		)
		item = frappe.db.get_value(
			"SP Review Item", {"reference_name": doc.name, "category": cr.REVIEW_CATEGORY}, "summary"
		)
		self.assertIn("MSKU123 -24", item)
		self.assertFalse(frappe.db.exists("SP Task", {"reference_name": doc.name, "status": "Open"}))

	def test_a_statement_that_agrees_is_matched_with_nothing_for_the_admin(self):
		doc = self.type_statement(self.sheet(), "MSKU123")
		self.assertEqual(self.as_user(self.keeper, cr.finish, doc.name)["status"], cr.MATCHED)
		self.assertFalse(frappe.db.exists("SP Review Item", {"reference_name": doc.name}))

	def test_finishing_needs_the_statement_and_a_note_on_each_difference(self):
		doc = self.sheet()
		untyped = self.line(doc, "MSKU123")
		self.assertEqual(
			(untyped.line_status, untyped.diff, doc.differences), ("", 0, 0)
		)  # nothing typed yet
		frappe.db.set_value(cr.RECONCILIATION, doc.name, "statement_file", STATEMENT)
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.keeper, cr.finish, doc.name)  # the statement's figures are not typed
		frappe.db.set_value(cr.RECONCILIATION, doc.name, "statement_file", None)
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.keeper, cr.finish, doc.name)  # no statement yet
		doc = self.type_statement(doc, "MSKU123", supplier_remaining=1200)
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.keeper, cr.finish, doc.name)  # the difference has no note

	def test_a_finished_reconciliation_keeps_its_figures(self):
		doc = self.type_statement(self.sheet(), "MSKU123")
		self.as_user(self.keeper, cr.finish, doc.name)
		doc = frappe.get_doc(cr.RECONCILIATION, doc.name)
		doc.lines[0].supplier_remaining = 1
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_figures_are_as_of_the_months_last_day(self):
		later = self.container("MSKU999", 2, nowdate())  # arrived this month
		doc = self.sheet()
		numbers = [l.container_no for l in doc.lines]
		self.assertIn("MSKU123", numbers)
		self.assertNotIn(later.container_no, numbers)
		self.assertEqual(cr.our_figures(self.msku.name, nowdate())["our_returned"], 33)
		self.assertEqual(cr.our_figures(self.msku.name, self.month_end)["our_returned"], 0)

	def test_one_sheet_a_month_and_only_the_store_keeper_or_admin(self):
		waiting = cr.due_count(self.keeper)
		doc = self.sheet()
		self.assertNotIn(doc.name, cr.create_monthly())
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other, cr.finish, doc.name)
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other, cr.load, doc.name)
		self.assertEqual(cr.due_count(self.keeper), waiting + 1)
		self.assertEqual(cr.due_count(self.other), 0)

	def test_the_store_home_card_counts_the_sheets_waiting(self):
		from smart_power.dashboards.cards import consignment_reco_due

		waiting = cr.due_count(self.keeper)
		self.sheet()
		card = consignment_reco_due(self.keeper)
		self.assertEqual((card["value"], card["route_options"]), (waiting + 1, {"status": cr.DRAFT}))
		self.assertIsNone(consignment_reco_due(self.other))
