"""The contract PDF (SP-75): the parties, the periods, the schedule and cheques annex, and a
signed contract that keeps the clauses it was signed with."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_months, flt, today

from smart_power.sp_core.documents import TEMPLATE, published, seed_contract_template
from smart_power.sp_core.printing import ar_words
from smart_power.sp_sales.quotation import approve_version
from smart_power.sp_stations.contract import make_contract
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import (
	INSTALL_DAYS,
	SUPPLY_DAYS,
	load_erpnext_test_data,
	make_quotation,
	sign_contract,
)

load_erpnext_test_data()

COMPANY = "_Test Company"
PRINT_FORMAT = "SP Contract"
INSTALMENTS, CHEQUES = 12, 4
NATIONAL_ID = "29001011234567"


class TestContractPrint(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		seed_contract_template()

	def setUp(self):
		if frappe.utils.get_assets_json() is None:
			patcher = patch("frappe.utils.get_assets_json", return_value={})
			patcher.start()
			self.addCleanup(patcher.stop)

	def order(self, rate=120000):
		quote = make_quotation(rate=rate, valid_days=3)
		quote.submit()
		approve_version(quote.name)
		return frappe.get_doc("Sales Order", make_contract(quote.sp_case)["sales_order"])

	def print_of(self, so):
		return frappe.get_print("Sales Order", so.name, PRINT_FORMAT, doc=so)

	def new_version(self, supply_text):
		"""The admin edits the supply clause in a new version and publishes it."""
		current = frappe.get_doc(TEMPLATE, published("Contract"))
		copy = frappe.get_doc(TEMPLATE, current.new_version())
		for row in copy.blocks:
			if row.block_key == "supply_period":
				row.body = f"<p>{supply_text}</p>"
		copy.save()
		copy.publish()
		return copy.name

	def test_12_instalments_and_4_cheques_print_with_the_total_in_figures_and_words(self):
		so = self.order()
		total = flt(so.rounded_total or so.grand_total)
		so.payment_terms_template = None
		so.set("payment_schedule", [])
		for month in range(INSTALMENTS):
			so.append(
				"payment_schedule",
				{
					"due_date": add_months(today(), month),
					"invoice_portion": 100 / INSTALMENTS,
					"payment_amount": total / INSTALMENTS,
				},
			)
		for n in range(CHEQUES):
			so.append(
				"sp_cheques",
				{"cheque_no": f"75000{n}", "due_date": add_months(today(), n), "amount": total / CHEQUES},
			)
		so.save()
		html = self.print_of(so)
		schedule = html.split("sp-contract-schedule", 1)[1].split("</table>", 1)[0]
		cheques = html.split("sp-contract-cheques", 1)[1].split("</table>", 1)[0]
		self.assertEqual(schedule.count("<tr>") - 1, INSTALMENTS)  # less the heading row
		self.assertEqual(cheques.count("<tr>") - 1, CHEQUES)
		self.assertIn(ar_words(total), html)
		self.assertIn(frappe.utils.fmt_money(total, currency=so.currency).split(" ")[0], html)

	def test_the_parties_and_the_periods_print(self):
		so = self.order()
		frappe.db.set_value("Customer", so.customer, "sp_national_id", NATIONAL_ID)
		self.addCleanup(frappe.db.set_value, "Customer", so.customer, "sp_national_id", None)
		so.sp_supply_days, so.sp_install_days = SUPPLY_DAYS, INSTALL_DAYS
		so.save()
		html = self.print_of(so)
		self.assertIn("sp-contract-parties", html)
		self.assertIn(NATIONAL_ID, html)
		self.assertIn(f'<span class="sp-num">{SUPPLY_DAYS}</span> يوماً', html)
		self.assertIn(f'<span class="sp-num">{INSTALL_DAYS}</span> يوماً', html)

	def test_a_contract_is_not_signed_without_its_periods(self):
		so = self.order()
		with self.assertRaises(frappe.ValidationError):
			so.submit()
		so.reload()
		so.sp_supply_days = SUPPLY_DAYS
		with self.assertRaises(frappe.ValidationError):
			so.submit()  # the installation days still missing

	def test_a_signed_contracts_days_do_not_change(self):
		so = sign_contract(self.order())
		so.reload()
		so.sp_supply_days = SUPPLY_DAYS + 1
		with self.assertRaises(frappe.ValidationError):
			so.save()

	def test_a_deposit_signs_without_the_days_and_they_are_filled_in_later(self):
		so = self.order()
		so.flags.sp_from_deposit = True
		so.submit()
		so.reload()
		self.assertEqual(so.sp_contract_template, published("Contract"))
		so.sp_supply_days, so.sp_install_days = SUPPLY_DAYS, INSTALL_DAYS
		so.save()  # filled in once, after the signing
		self.assertEqual(frappe.db.get_value("Sales Order", so.name, "sp_supply_days"), SUPPLY_DAYS)

	def test_a_published_clause_reaches_the_next_contract_and_not_a_signed_one(self):
		signed = sign_contract(self.order())
		version = signed.sp_contract_template
		self.assertEqual(version, published("Contract"))
		before = self.print_of(signed)
		self.new_version("نص التوريد الجديد خلال {supply_days} يوماً")
		self.assertNotEqual(published("Contract"), version)

		after = self.print_of(frappe.get_doc("Sales Order", signed.name))
		self.assertNotIn("نص التوريد الجديد", after)
		self.assertEqual(after, before)  # the signed contract prints as it did

		draft = self.order(rate=90000)
		self.assertIn("نص التوريد الجديد", self.print_of(draft))
		signed_next = sign_contract(draft.name)  # printing changes the doc in memory
		self.assertEqual(signed_next.sp_contract_template, published("Contract"))
