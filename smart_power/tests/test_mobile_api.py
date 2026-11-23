"""Mobile API v1 (SP-148): sign-in and tokens, a station's site view with no money and only for
the people on it, the rate limit, stable error codes, sync, tasks and the form schema."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.test_api import FrappeAPITestCase
from frappe.utils.password import update_password

from smart_power.api.mobile.v1 import auth, common, forms, stations, sync, tasks
from smart_power.sp_stock import warehouses as wh
from smart_power.tests.utils import load_erpnext_test_data, make_user

load_erpnext_test_data()

COMPANY = "_Test Company"


def keys_anywhere(value) -> set:
	if isinstance(value, dict):
		return set(value) | {k for v in value.values() for k in keys_anywhere(v)}
	if isinstance(value, list):
		return {k for v in value for k in keys_anywhere(v)}
	return set()


class TestMobileAPI(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		wh.seed_warehouses(COMPANY)
		cls.mostafa = make_user("sp.mob.mostafa@example.com", ("installation_manager",))
		cls.driver = make_user("sp.mob.driver@example.com", ("driver",))
		cls.station = frappe.get_doc(
			{
				"doctype": "SP Station",
				"customer": "_Test Customer",
				"company": COMPANY,
				"execution_owner": cls.mostafa,
			}
		).insert()

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		for user in (self.mostafa, self.driver):
			frappe.cache.delete(common.rate_key(user))

	def as_user(self, user):
		frappe.set_user(user)
		frappe.local.response = frappe._dict()

	def test_the_driver_is_not_on_the_station(self):
		self.as_user(self.driver)
		result = stations.get(self.station.name)
		self.assertEqual(result["error"]["code"], "NOT_PERMITTED")
		self.assertEqual(frappe.local.response.http_status_code, 403)
		self.assertEqual(stations.get("NO-SUCH")["error"]["code"], "NOT_FOUND")

	def test_the_site_view_has_no_money(self):
		self.as_user(self.mostafa)
		result = stations.get(self.station.name)
		self.assertEqual(result["name"], self.station.name)
		money = {k for k in keys_anywhere(result) if common.is_money(k)}
		self.assertEqual(money, set())
		self.assertIn("capacity_kw_total", result)  # a total that is not money stays
		self.assertIn(self.station.name, [s["name"] for s in stations.mine()])

	def test_the_next_call_past_the_limit_gets_429(self):
		self.as_user(self.mostafa)
		limit = common.RATE_DEFAULT
		results = [stations.mine() for _ in range(limit + 30)]  # 150 in a minute
		self.assertIsInstance(results[limit - 1], list)
		self.assertEqual(results[limit]["error"]["code"], "RATE_LIMITED")
		self.assertEqual(frappe.local.response.http_status_code, 429)

	def test_money_is_stripped_at_any_depth(self):
		data = {
			"name": "x",
			"payment_amount": 5,
			"rows": [{"sp_cost": 1, "qty": 2, "base_rate": 3}],
			"operation_date": "d",
		}
		self.assertEqual(common.safe(data), {"name": "x", "rows": [{"qty": 2}], "operation_date": "d"})

	def test_a_phone_signs_in_and_a_wrong_password_counts(self):
		update_password(self.mostafa, "Mob1le-Test-Pass")
		frappe.db.set_value("User", self.mostafa, "sp_must_change_password", 0)
		with (
			patch.object(common, "device_id", return_value="PHONE-1"),
			patch.object(auth, "device_id", return_value="PHONE-1"),
		):
			frappe.set_user("Guest")
			result = auth.login(self.mostafa, "Mob1le-Test-Pass", "Test phone")
			self.assertEqual(result["user"], self.mostafa)
			api_key = frappe.db.get_value("User", self.mostafa, "api_key")
			self.assertTrue(result["token"].startswith(f"{api_key}:"))
			self.assertTrue(
				frappe.db.get_value(common.DEVICE, {"user": self.mostafa, "device_id": "PHONE-1"}, "active")
			)
			before = frappe.db.get_value("User", self.mostafa, "sp_failed_logins") or 0
			wrong = auth.login(self.mostafa, "wrong", None)
			self.assertEqual(wrong["error"]["code"], "AUTH")
			self.assertEqual(frappe.db.get_value("User", self.mostafa, "sp_failed_logins"), before + 1)
			frappe.db.set_value("User", self.mostafa, "sp_must_change_password", 1)
			self.assertEqual(
				auth.login(self.mostafa, "Mob1le-Test-Pass", None)["error"]["code"], "PASSWORD_CHANGE"
			)
			frappe.db.set_value("User", self.mostafa, "sp_must_change_password", 0)
			device = frappe.db.get_value(common.DEVICE, {"user": self.mostafa, "device_id": "PHONE-1"})
			frappe.db.set_value(common.DEVICE, device, "revoked_on", frappe.utils.now_datetime())
			self.as_user(self.mostafa)
			self.assertEqual(stations.mine()["error"]["code"], "DEVICE_REVOKED")
			frappe.set_user("Guest")
			self.assertEqual(
				auth.login(self.mostafa, "Mob1le-Test-Pass", None)["error"]["code"], "DEVICE_REVOKED"
			)

	def test_sync_push_takes_each_item_on_its_own(self):
		self.as_user(self.mostafa)
		saved = {}

		def save(values):
			if values.get("bad"):
				frappe.throw("bad item")
			return saved.setdefault(values["client_uuid"], f"REC-{len(saved) + 1}")

		with patch.dict(sync.KINDS, {"Test Kind": save}):
			result = sync.push(
				[
					{"doctype": "Test Kind", "client_uuid": "u1", "values": {}},
					{"doctype": "Test Kind", "client_uuid": "u2", "values": {"bad": 1}},
					{"doctype": "Nope", "client_uuid": "u3"},
					{"doctype": "Test Kind", "client_uuid": "u1", "values": {}},  # sent again
				]
			)["results"]
		self.assertEqual([r["ok"] for r in result], [True, False, False, True])
		self.assertEqual((result[0]["name"], result[3]["name"]), ("REC-1", "REC-1"))
		self.assertEqual(result[1]["error"]["code"], "VALIDATION")
		pulled = sync.pull()
		self.assertIn("server_time", pulled)
		self.assertTrue(pulled["lists"])

	def test_tasks_and_the_form_schema_keep_money_out(self):
		from smart_power.sp_core.inbox import create_task

		create_task("Other", "SP Station", self.station.name, self.mostafa, "زيارة الموقع", amount=500)
		self.as_user(self.mostafa)
		rows = tasks.list()["tasks"]
		self.assertTrue(rows)
		self.assertNotIn("amount", keys_anywhere(rows))
		self.assertEqual(tasks.action(rows[0]["name"], "fly")["error"]["code"], "VALIDATION")
		fields = {f["fieldname"] for f in forms.schema("SP Station")["fields"]}
		self.assertIn("customer_name", fields)
		self.assertNotIn("agreed_amount", fields)  # the station's money level, not given to him


class TestMobileOverHTTP(FrappeAPITestCase):
	"""One real round trip with the token. The request runs on its own connection, so the user is
	committed and removed again."""

	USER = "sp.mob.http@example.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.db.rollback()  # commit the user alone, nothing the test setup prepared before it
		make_user(cls.USER, ("installation_manager",))
		update_password(cls.USER, "Mob1le-Http-Pass")
		frappe.db.set_value("User", cls.USER, "sp_must_change_password", 0)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.db.rollback()
		for dt, field in ((common.DEVICE, "user"), ("Activity Log", "user"), ("Sessions", "user")):
			frappe.db.delete(dt, {field: cls.USER})
		for contact in frappe.get_all("Contact", {"user": cls.USER}, pluck="name"):
			frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
		frappe.delete_doc("User", cls.USER, force=True, ignore_permissions=True)
		frappe.db.delete("Deleted Document", {"deleted_name": ("in", [cls.USER, cls.USER.split("@")[0]])})
		frappe.db.delete("Permission Log", {"for_doctype": "User", "for_document": cls.USER})
		frappe.db.commit()
		super().tearDownClass()

	def test_sign_in_then_call_with_the_token(self):
		login = self.post(
			self.method("smart_power.api.mobile.v1.auth.login"), {"usr": self.USER, "pwd": "Mob1le-Http-Pass"}
		)
		self.assertEqual(login.status_code, 200, login.json)
		token = login.json["message"]["token"]
		mine = self.get(
			self.method("smart_power.api.mobile.v1.stations.mine"),
			headers={"Authorization": f"token {token}"},
		)
		self.assertEqual(mine.status_code, 200, mine.json)
		self.assertIsInstance(mine.json["message"], list)
		wrong = self.post(
			self.method("smart_power.api.mobile.v1.auth.login"), {"usr": self.USER, "pwd": "nope"}
		)
		self.assertEqual((wrong.status_code, wrong.json["message"]["error"]["code"]), (401, "AUTH"))
