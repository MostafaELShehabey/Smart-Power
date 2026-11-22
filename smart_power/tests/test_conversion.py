"""R6 Conversion (SP-144): a period's requests, followed to quoted and won, by channel and person,
and the lost reasons. The cases are dated to a past March, so the site's own cases stay out."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, get_datetime

from smart_power.sp_core.services.lists import by_code
from smart_power.sp_sales import conversion as cv
from smart_power.tests.test_case import make_case
from smart_power.tests.utils import make_user

MARCH = ("2020-03-01", "2020-03-31")
REQUESTS, QUOTED, WON = 40, 30, 9  # the story's March via calls
SHOWROOM = 5
FAST, SLOW = 3, 30  # hours to the quote: within 24 h, and late


class TestConversion(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.creator = make_user("sp.cv.creator@example.com", ("quote_creator",))
		cls.price_check = by_code("Lost Reason", "PRICE_CHECK_ONLY")
		cls.cases = [cls.case("Call", i) for i in range(REQUESTS)]
		cls.showroom = [cls.case("Showroom", i) for i in range(SHOWROOM)]

	@classmethod
	def case(cls, channel, i):
		doc = make_case(channel=channel, quote_creator=cls.creator)
		opened = get_datetime(f"2020-03-{1 + i % 28:02d} 09:00:00")
		values = {"creation": opened, "quote_due_at": add_to_date(opened, hours=24)}
		if channel == "Call" and i < QUOTED:
			values["quote_sent_at"] = add_to_date(opened, hours=FAST if i < QUOTED // 2 else SLOW)
		if channel == "Call" and i < WON:
			values["status"] = "Won"
		elif channel == "Call" and i >= QUOTED:
			values.update(status="Lost", lost_reason=cls.price_check)
		frappe.db.set_value("SP Case", doc.name, values, update_modified=False)
		return doc.name

	def report(self, **filters):
		return cv.rows({"from_date": MARCH[0], "to_date": MARCH[1], **filters})

	def test_march_by_channel_shows_40_30_9_and_a_30_percent_win_rate(self):
		call = next(r for r in self.report(group_by=cv.CHANNEL) if r["key"] == "Call")
		self.assertEqual((call["requests"], call["quoted"], call["won"]), (REQUESTS, QUOTED, WON))
		self.assertEqual(call["win_rate"], 30)
		self.assertEqual(call["quote_rate"], 75)
		self.assertEqual(call["in_24h"], 37.5)  # 15 of 40 quoted by their deadline
		self.assertEqual(call["avg_hours"], (FAST + SLOW) / 2)

	def test_the_total_adds_the_channels(self):
		total = next(r for r in self.report() if r.get("is_total"))
		self.assertEqual(
			(total["requests"], total["quoted"], total["won"]), (REQUESTS + SHOWROOM, QUOTED, WON)
		)

	def test_by_quote_creator(self):
		mine = next(r for r in self.report(group_by=cv.CREATOR) if r["key"] == self.creator)
		self.assertEqual(mine["requests"], REQUESTS + SHOWROOM)

	def test_lost_reasons_count_price_check_only(self):
		rows = self.report(group_by=cv.REASON)
		price = next(r for r in rows if r["key"] == self.price_check)
		self.assertEqual((price["lost"], price["share"]), (REQUESTS - QUOTED, 100))

	def test_the_system_type_filter(self):
		pump = by_code("System Type", "PUMP")
		frappe.get_doc("SP Case", self.showroom[0]).append("system_types", {"system_type": pump}).db_insert()
		total = next(r for r in self.report(system_type=pump) if r.get("is_total"))
		self.assertEqual(total["requests"], 1)

	def test_a_period_with_no_requests(self):
		rows = cv.rows({"from_date": "2019-01-01", "to_date": "2019-01-31"})
		self.assertEqual([(r["requests"], r["win_rate"]) for r in rows], [(0, 0.0)])
