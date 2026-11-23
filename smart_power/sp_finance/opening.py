"""A15 Opening balances (SP-160): the cutover sheet for 1-1-2027, prepared, checked, then posted once.

The accountant downloads the template, fills it with the 31-12 balances and attaches it to the
company's SP Opening Balance. Check reads every sheet and lists each problem with its sheet and
row, and the figures it will post; nothing is saved. The admin then posts it once (a background
job, all or nothing), and Reconcile compares the trial balance on the opening date with the
template's Trial Balance sheet, line by line.

    Accounts       the official, transit and fixed-asset accounts (the winch and the Jumbo car at
                   book value) and any other balance-sheet line: one opening Journal Entry
    Custody        the open custody per holder: a given SP Custody each, settled as usual
    Customers      what each customer owes: an opening Sales Invoice each
    Suppliers      what is owed to each supplier (Africa System among them): an opening Purchase
                   Invoice each
    Stock          the count of 29-30 Dec with the new item codes: an opening Stock Reconciliation
                   per warehouse
    Consignment    the goods suppliers keep with us, per container (SP-91)
    Trial Balance  the 31-12 list the opening must match (Reconcile)

The opening documents go through the Temporary Opening account, which a last entry clears into
Opening Balance Equity: the owner's equity is the balancing figure.

    template()          the workbook to fill
    run_check(name)     check the attached workbook (nothing saved but the result)
    post(name)          the admin posts it, once
    reconcile(name)     the trial balance on the opening date against the template's
"""

import hashlib
import io
import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now_datetime

OPENING = "SP Opening Balance"
DRAFT, CHECKED, POSTED, FAILED = "Draft", "Checked", "Posted", "Failed"
ADMIN_ROLES = ("SP Admin", "System Manager")
EQUITY_ACCOUNT, TEMPORARY_ACCOUNT = "Opening Balance Equity", "Temporary Opening"
NOT_ON_ACCOUNTS = ("Receivable", "Payable", "Stock")  # these come through their own sheets
ROUNDING = 0.005  # sp-allow-number: half a piastre
DIGITS = 2  # sp-allow-number: currency precision
HINT = "#"  # a row whose first cell starts with it is a hint, not data
FIRST_DATA_ROW = 2  # sp-allow-number: the row under the header, as the workbook numbers it
JOB_TIMEOUT = 3600  # sp-allow-number: an hour for a large opening

ACCOUNTS, CUSTODY, CUSTOMERS, SUPPLIERS = "Accounts", "Custody", "Customers", "Suppliers"
STOCK, CONSIGNMENT, TRIAL = "Stock", "Consignment", "Trial Balance"
# sheet → its columns, and the Arabic hint row under them
SHEETS = {
	ACCOUNTS: (
		("account", "الحساب"),
		("debit", "مدين"),
		("credit", "دائن"),
		("note", "ملاحظة"),
	),
	CUSTODY: (("holder", "صاحب العهدة"), ("amount", "المبلغ المفتوح"), ("given_on", "تاريخ العهدة")),
	CUSTOMERS: (
		("customer", "العميل"),
		("amount", "المستحق عليه"),
		("invoice_date", "تاريخ الدين"),
		("due_date", "تاريخ الاستحقاق"),
	),
	SUPPLIERS: (
		("supplier", "المورد"),
		("amount", "المستحق له"),
		("invoice_date", "تاريخ الفاتورة"),
		("due_date", "تاريخ الاستحقاق"),
		("bill_no", "رقم فاتورة المورد"),
	),
	STOCK: (
		("warehouse", "المخزن"),
		("item_code", "كود الصنف"),
		("qty", "الكمية"),
		("valuation_rate", "سعر التكلفة"),
	),
	CONSIGNMENT: (
		("supplier", "المورد"),
		("item_code", "كود الصنف"),
		("container_no", "رقم الحاوية"),
		("location", "المكان"),
		("pallets", "عدد البالتات"),
		("per_pallet", "الألواح في البالتة"),
		("received_on", "تاريخ الاستلام"),
	),
	TRIAL: (("account", "الحساب"), ("debit", "مدين"), ("credit", "دائن")),
}


def _is_admin() -> bool:
	return frappe.session.user == "Administrator" or bool(set(ADMIN_ROLES) & set(frappe.get_roles()))


def name_for(company: str) -> str:
	"""One opening per company: OB-<abbr>."""
	name = f"OB-{frappe.get_cached_value('Company', company, 'abbr')}"
	if frappe.db.exists(OPENING, name):
		frappe.throw(_("The opening of {0} is already prepared in {1}.").format(company, name))
	return name


def validate(doc) -> None:
	if doc.is_new():
		doc.status = DRAFT
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	locked = ("company", "opening_date", "workbook", "station_mode")
	if before.status == POSTED and any(before.get(f) != doc.get(f) for f in locked):
		frappe.throw(_("The opening is posted: it no longer changes."))
	if before.status == CHECKED and any(before.get(f) != doc.get(f) for f in locked):
		doc.status, doc.workbook_hash = DRAFT, None  # check it again


def on_trash(doc) -> None:
	if doc.status == POSTED:
		frappe.throw(_("A posted opening cannot be deleted."))


# --- the template ----------------------------------------------------------------------------------


@frappe.whitelist()
def template() -> None:
	"""The workbook to fill: a sheet per section, its columns, and a hint row in Arabic."""
	from openpyxl import Workbook

	frappe.has_permission(OPENING, "read", throw=True)
	book = Workbook()
	book.remove(book.active)
	for sheet, columns in SHEETS.items():
		ws = book.create_sheet(sheet)
		ws.append([key for key, _hint in columns])
		ws.append([f"{HINT} {hint}" if i == 0 else hint for i, (_key, hint) in enumerate(columns)])
	out = io.BytesIO()
	book.save(out)
	frappe.response.filename = "opening-balances.xlsx"
	frappe.response.filecontent = out.getvalue()
	frappe.response.type = "binary"


# --- reading the workbook --------------------------------------------------------------------------


def _file(doc):
	if not doc.workbook:
		frappe.throw(_("Attach the filled workbook first."))
	return frappe.get_doc("File", {"file_url": doc.workbook})


def _hash(content: bytes) -> str:
	return hashlib.sha256(content).hexdigest()


def read(content: bytes) -> dict[str, list[dict]]:
	"""{sheet: rows}; each row a dict by column key, with its row number in the workbook."""
	from openpyxl import load_workbook

	book = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
	out = {}
	for sheet, columns in SHEETS.items():
		if sheet not in book.sheetnames:
			out[sheet] = []
			continue
		rows = list(book[sheet].iter_rows(values_only=True))
		header = [str(c or "").strip().lower() for c in (rows[0] if rows else [])]
		keys = {key for key, _hint in columns}
		out[sheet] = []
		for number, values in enumerate(rows[1:], start=FIRST_DATA_ROW):
			first = values[0] if values else None
			if all(v in (None, "") for v in values) or str(first or "").strip().startswith(HINT):
				continue
			row = {h: v for h, v in zip(header, values, strict=False) if h in keys}
			row["_row"] = number
			out[sheet].append(row)
	return out


# --- the plan: every row resolved, every problem named --------------------------------------------


class Plan:
	"""The workbook resolved against the site: what will be posted, and every problem found."""

	def __init__(self, doc, sheets: dict):
		self.doc, self.company, self.sheets = doc, doc.company, sheets
		self.on = getdate(doc.opening_date)
		self.errors: list[dict] = []
		self.temporary = self._named_account(TEMPORARY_ACCOUNT)
		self.equity = self._named_account(EQUITY_ACCOUNT)
		self.lines, self.custody, self.customers, self.suppliers = [], [], [], []
		self.stock, self.consignment, self.trial = {}, [], []
		self.build()

	# problems and lookups

	def error(self, sheet: str, row, message: str) -> None:
		self.errors.append({"sheet": _(sheet), "row": row.get("_row") if row else None, "message": message})

	def _named_account(self, name: str) -> str | None:
		found = frappe.db.get_value("Account", {"company": self.company, "is_group": 0, "account_name": name})
		if not found:
			self.error(ACCOUNTS, None, _("The company has no {0} account.").format(_(name)))
		return found

	def account(self, value):
		value = str(value or "").strip()
		if not value:
			return None
		if frappe.db.exists("Account", {"name": value, "company": self.company, "is_group": 0}):
			return value
		return frappe.db.get_value("Account", {"account_name": value, "company": self.company, "is_group": 0})

	@staticmethod
	def party(doctype: str, value, name_field: str, mobile: bool = False):
		value = str(value or "").strip()
		if not value:
			return None
		if frappe.db.exists(doctype, value):
			return value
		found = frappe.db.get_value(doctype, {name_field: value})
		if not found and mobile:
			found = frappe.db.get_value(doctype, {"sp_mobile": value})
		return found

	@staticmethod
	def user(value):
		value = str(value or "").strip()
		if not value:
			return None
		if frappe.db.exists("User", value):
			return value
		return frappe.db.get_value("User", {"full_name": value, "enabled": 1})

	def date(self, sheet, row, key, default=None):
		value = row.get(key)
		if value in (None, ""):
			return default
		try:
			day = getdate(value)
		except Exception:
			self.error(sheet, row, _("{0} is not a date.").format(key))
			return default
		if day > self.on:
			self.error(sheet, row, _("{0} is after the opening date.").format(key))
		return day

	def amount(self, sheet, row, key="amount", allow_zero=False) -> float:
		try:
			value = flt(row.get(key), DIGITS)
		except Exception:
			value = 0.0
		if value < 0 or (not allow_zero and value <= 0):
			self.error(sheet, row, _("Enter a positive {0}.").format(key))
		return value

	# the sheets

	def build(self) -> None:
		self._accounts()
		self._custody()
		self._parties(CUSTOMERS, "Customer", "customer", "customer_name", self.customers, mobile=True)
		self._parties(SUPPLIERS, "Supplier", "supplier", "supplier_name", self.suppliers)
		self._stock()
		self._consignment()
		self._trial()

	def _accounts(self) -> None:
		for row in self.sheets.get(ACCOUNTS, []):
			account = self.account(row.get("account"))
			debit, credit = flt(row.get("debit"), DIGITS), flt(row.get("credit"), DIGITS)
			if not account:
				self.error(ACCOUNTS, row, _("Account {0} is not found.").format(row.get("account") or ""))
				continue
			kind, account_type = frappe.db.get_value("Account", account, ["sp_account_kind", "account_type"])
			if account_type in NOT_ON_ACCOUNTS:
				self.error(
					ACCOUNTS,
					row,
					_("{0} comes through its own sheet (customers, suppliers or stock).").format(account),
				)
			elif kind == "Custody":
				self.error(ACCOUNTS, row, _("Open custody goes on the Custody sheet: {0}.").format(account))
			elif account in (self.temporary, self.equity):
				self.error(ACCOUNTS, row, _("{0} is the opening's own account.").format(account))
			elif (debit > 0) == (credit > 0) or debit < 0 or credit < 0:
				self.error(ACCOUNTS, row, _("Enter either a debit or a credit."))
			else:
				self.lines.append({"account": account, "debit": debit, "credit": credit, "_row": row["_row"]})

	def _custody(self) -> None:
		for row in self.sheets.get(CUSTODY, []):
			holder = self.user(row.get("holder"))
			amount = self.amount(CUSTODY, row)
			if not holder:
				self.error(CUSTODY, row, _("{0} is not a user.").format(row.get("holder") or ""))
				continue
			self.custody.append(
				{"holder": holder, "amount": amount, "given_on": self.date(CUSTODY, row, "given_on", self.on)}
			)

	def _parties(self, sheet, doctype, key, name_field, into, mobile=False) -> None:
		for row in self.sheets.get(sheet, []):
			party = self.party(doctype, row.get(key), name_field, mobile)
			amount = self.amount(sheet, row)
			if not party:
				self.error(sheet, row, _("{0} {1} is not found.").format(_(doctype), row.get(key) or ""))
				continue
			posting = self.date(sheet, row, "invoice_date", self.on)
			into.append(
				{
					"party": party,
					"amount": amount,
					"posting_date": posting,
					"due_date": self.date(sheet, row, "due_date", None) or posting,
					"bill_no": str(row.get("bill_no") or "").strip() or None,
				}
			)

	def _stock(self) -> None:
		for row in self.sheets.get(STOCK, []):
			warehouse = str(row.get("warehouse") or "").strip()
			if not frappe.db.exists("Warehouse", {"name": warehouse, "company": self.company, "is_group": 0}):
				warehouse = frappe.db.get_value(
					"Warehouse", {"warehouse_name": warehouse, "company": self.company, "is_group": 0}
				)
			item = str(row.get("item_code") or "").strip()
			if not warehouse:
				self.error(STOCK, row, _("Warehouse {0} is not found.").format(row.get("warehouse") or ""))
				continue
			if not frappe.db.get_value("Item", item, "is_stock_item"):
				self.error(STOCK, row, _("{0} is not a stock item.").format(item))
				continue
			qty = self.amount(STOCK, row, "qty", allow_zero=True)
			if not qty:
				continue  # nothing counted: nothing to open
			rate = self.amount(STOCK, row, "valuation_rate")
			lines = self.stock.setdefault(warehouse, {})
			if item in lines:
				self.error(STOCK, row, _("{0} is counted twice in {1}.").format(item, warehouse))
				continue
			lines[item] = {"item_code": item, "warehouse": warehouse, "qty": qty, "valuation_rate": rate}

	def _consignment(self) -> None:
		for row in self.sheets.get(CONSIGNMENT, []):
			supplier = self.party("Supplier", row.get("supplier"), "supplier_name")
			item = str(row.get("item_code") or "").strip()
			if not supplier:
				self.error(
					CONSIGNMENT, row, _("Supplier {0} is not found.").format(row.get("supplier") or "")
				)
				continue
			if not frappe.db.get_value("Supplier", supplier, "sp_is_consignment_owner"):
				self.error(
					CONSIGNMENT, row, _("{0} does not keep goods with us on consignment.").format(supplier)
				)
				continue
			if not frappe.db.exists("Item", item):
				self.error(CONSIGNMENT, row, _("{0} is not an item.").format(item))
				continue
			self.consignment.append(
				{
					"supplier": supplier,
					"item": item,
					"container_no": str(row.get("container_no") or "").strip() or None,
					"location": str(row.get("location") or "").strip() or None,
					"pallets": cint(self.amount(CONSIGNMENT, row, "pallets")),
					"per_pallet": cint(self.amount(CONSIGNMENT, row, "per_pallet")),
					"received_on": self.date(CONSIGNMENT, row, "received_on", self.on),
				}
			)

	def _trial(self) -> None:
		for row in self.sheets.get(TRIAL, []):
			account = self.account(row.get("account"))
			if not account:
				self.error(TRIAL, row, _("Account {0} is not found.").format(row.get("account") or ""))
				continue
			self.trial.append(
				{"account": account, "net": flt(row.get("debit"), DIGITS) - flt(row.get("credit"), DIGITS)}
			)
		if abs(sum(t["net"] for t in self.trial)) > ROUNDING:
			self.error(TRIAL, None, _("The trial balance's debits and credits are not equal."))

	# the figures

	def stock_value(self, in_ledger: bool = False) -> float:
		"""The counted stock's value; with in_ledger, only when the company posts stock to the
		ledger (perpetual inventory), as only then does it move Temporary Opening."""
		from erpnext import is_perpetual_inventory_enabled

		if in_ledger and not is_perpetual_inventory_enabled(self.company):
			return 0.0
		return sum(
			flt(i["qty"]) * flt(i["valuation_rate"]) for lines in self.stock.values() for i in lines.values()
		)

	def through_temporary(self) -> float:
		"""What the opening documents credit to Temporary Opening, less what they debit."""
		return (
			sum(c["amount"] for c in self.customers)
			+ self.stock_value(in_ledger=True)
			+ sum(c["amount"] for c in self.custody)
			- sum(s["amount"] for s in self.suppliers)
		)

	def equity_credit(self) -> float:
		"""The balancing figure: what Opening Balance Equity is credited with (a debit if below 0)."""
		lines = sum(r["debit"] - r["credit"] for r in self.lines)
		return flt(lines + self.through_temporary(), DIGITS)

	def summary(self) -> dict:
		sections = [
			(ACCOUNTS, len(self.lines), sum(r["debit"] for r in self.lines)),
			(CUSTODY, len(self.custody), sum(c["amount"] for c in self.custody)),
			(CUSTOMERS, len(self.customers), sum(c["amount"] for c in self.customers)),
			(SUPPLIERS, len(self.suppliers), sum(s["amount"] for s in self.suppliers)),
			(STOCK, sum(len(v) for v in self.stock.values()), self.stock_value()),
			(CONSIGNMENT, len(self.consignment), 0.0),
			(TRIAL, len(self.trial), sum(t["net"] for t in self.trial if t["net"] > 0)),
		]
		return {
			"errors": self.errors,
			"sections": [{"sheet": _(s), "rows": n, "amount": flt(a, DIGITS)} for s, n, a in sections],
			"equity": self.equity_credit(),
			"opening_date": str(self.on),
		}


def _content(doc) -> bytes:
	content = _file(doc).get_content()
	return content.encode() if isinstance(content, str) else content


def _plan(doc) -> tuple[Plan, str]:
	content = _content(doc)
	return Plan(doc, read(content)), _hash(content)


@frappe.whitelist(methods=["POST"])
def run_check(name: str) -> dict:
	"""Check the attached workbook; the opening is Checked when nothing is wrong."""
	doc = frappe.get_doc(OPENING, name)
	doc.check_permission("write")
	if doc.status == POSTED:
		frappe.throw(_("The opening is posted."))
	plan, digest = _plan(doc)
	result = plan.summary()
	doc.db_set(
		{
			"check_json": json.dumps(result, default=str),
			"checked_on": now_datetime(),
			"status": DRAFT if result["errors"] else CHECKED,
			"workbook_hash": None if result["errors"] else digest,
		}
	)
	return result


# --- posting ---------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def post(name: str) -> str:
	"""The admin posts the checked opening, once, as a background job."""
	if not _is_admin():
		frappe.throw(_("Only the admin posts the opening."), frappe.PermissionError)
	doc = frappe.get_doc(OPENING, name)
	if doc.status != CHECKED:
		frappe.throw(_("Check the workbook first: only a checked opening is posted."))
	if _plan(doc)[1] != doc.workbook_hash:
		frappe.throw(_("The workbook changed since it was checked: check it again."))
	frappe.enqueue(
		run_post,
		queue="long",
		timeout=JOB_TIMEOUT,
		name=name,
		now=frappe.in_test,
		enqueue_after_commit=True,
	)
	return _("Posting started: the opening shows Posted when it is done.")


def run_post(name: str) -> None:
	"""All or nothing: on any error nothing stays posted, and the opening shows the error."""
	doc = frappe.get_doc(OPENING, name)
	try:
		plan, _digest = _plan(doc)
		if plan.errors:
			frappe.throw(_("The workbook has {0} problems: check it again.").format(len(plan.errors)))
		posted = Poster(doc, plan).run()
		doc.reload()
		doc.set("documents", [])
		for row in posted:
			doc.append("documents", row)
		doc.status, doc.posted_on, doc.posted_by, doc.error = (
			POSTED,
			now_datetime(),
			frappe.session.user,
			None,
		)
		doc.save(ignore_permissions=True)
		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep: a background job commits its own work
	except Exception:
		frappe.db.rollback()
		message = frappe.get_traceback(with_context=False).strip().splitlines()[-1]
		frappe.db.set_value(OPENING, name, {"status": FAILED, "error": message})
		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep: keep the failure for the admin to read
		else:
			raise


class Poster:
	"""Creates the opening documents from a resolved plan, in order, and lists them."""

	def __init__(self, doc, plan: Plan):
		self.doc, self.plan, self.company, self.on = doc, plan, doc.company, plan.on
		self.center = frappe.get_cached_value("Company", self.company, "cost_center")
		self.year = self.on.year
		self.posted: list[dict] = []

	def keep(self, sheet: str, doc, amount: float = 0.0) -> None:
		self.posted.append(
			{
				"sheet": _(sheet),
				"reference_doctype": doc.doctype,
				"reference_name": doc.name,
				"amount": amount,
			}
		)

	def run(self) -> list[dict]:
		self.accounts()
		self.invoices(CUSTOMERS, "Sales", "Customer", self.plan.customers, "OPN-SI")
		self.invoices(SUPPLIERS, "Purchase", "Supplier", self.plan.suppliers, "OPN-PI")
		self.stock()
		self.consignment()
		self.custody()
		self.extra()
		self.close_temporary()
		return self.posted

	def extra(self) -> None:
		"""Sections later stories add (stations, advances, winch jobs)."""

	def journal(self, lines: list[dict], remark: str):
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Opening Entry",
				"is_opening": "Yes",
				"company": self.company,
				"posting_date": self.on,
				"user_remark": remark,
				# its source is the opening, so it is not listed as a manual entry (SP-129)
				"sp_source_doctype": OPENING,
				"sp_source_name": self.doc.name,
				"accounts": [
					{
						"account": line["account"],
						"debit_in_account_currency": flt(line.get("debit")),
						"credit_in_account_currency": flt(line.get("credit")),
						"cost_center": line.get("cost_center") or self.center,
						**{k: line[k] for k in ("party_type", "party", "project") if line.get(k)},
					}
					for line in lines
				],
			}
		)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		return je

	def accounts(self) -> None:
		lines = [dict(r) for r in self.plan.lines]
		if not lines:
			return
		net = flt(sum(r["debit"] - r["credit"] for r in lines), DIGITS)
		if abs(net) > ROUNDING:
			side = "credit" if net > 0 else "debit"
			lines.append({"account": self.plan.equity, side: abs(net)})
		je = self.journal(lines, _("Opening balances on {0}").format(self.on))
		self.keep(ACCOUNTS, je, sum(r["debit"] for r in self.plan.lines))

	def invoices(self, sheet, invoice_type, party_type, rows, prefix) -> None:
		if not rows:
			return
		tool = frappe.new_doc("Opening Invoice Creation Tool")
		tool.company, tool.invoice_type = self.company, invoice_type
		for row in rows:
			tool.append(
				"invoices",
				{
					"party_type": party_type,
					"party": row["party"],
					"posting_date": row["posting_date"],
					"due_date": row["due_date"],
					"outstanding_amount": row["amount"],
					"qty": 1,
					"temporary_opening_account": self.plan.temporary,
					"item_name": _("Opening balance"),
					"invoice_number": row.get("bill_no"),
				},
			)
		doctype = f"{invoice_type} Invoice"
		base = f"{prefix}-{frappe.get_cached_value('Company', self.company, 'abbr')}-{self.year}-"
		taken = frappe.db.count(doctype, {"name": ("like", f"{base}%")})
		for i, values in enumerate(tool.get_invoices(), start=1):
			values.pop("invoice_number", None)
			if invoice_type == "Purchase" and rows[i - 1].get("bill_no"):
				values["bill_no"] = rows[i - 1]["bill_no"]
			invoice = frappe.get_doc(values)
			invoice.flags.ignore_mandatory = True
			invoice.flags.dont_auto_add_taxes = True
			invoice.flags.ignore_permissions = True
			invoice.insert(set_name=f"{base}{taken + i:04d}")  # sp-allow-number: 4-digit counter
			invoice.submit()
			self.keep(sheet, invoice, rows[i - 1]["amount"])

	def stock(self) -> None:
		for lines in self.plan.stock.values():
			sr = frappe.get_doc(
				{
					"doctype": "Stock Reconciliation",
					"purpose": "Opening Stock",
					"company": self.company,
					"posting_date": self.on,
					"set_posting_time": 1,
					"expense_account": self.plan.temporary,
					"cost_center": self.center,
					"items": list(lines.values()),
				}
			)
			sr.flags.ignore_permissions = True
			sr.insert()
			sr.submit()
			self.keep(STOCK, sr, sum(flt(i["qty"]) * flt(i["valuation_rate"]) for i in lines.values()))

	def consignment(self) -> None:
		for row in self.plan.consignment:
			container = frappe.get_doc(
				{"doctype": "SP Consignment Container", "company": self.company, **row}
			)
			container.flags.ignore_permissions = True
			container.insert()
			self.keep(CONSIGNMENT, container)

	def custody(self) -> None:
		for row in self.plan.custody:
			doc = frappe.get_doc(
				{
					"doctype": "SP Custody",
					"holder": row["holder"],
					"company": self.company,
					"given_on": row["given_on"],
					"from_account": self.plan.temporary,
					"amount": row["amount"],
				}
			)
			doc.flags.sp_opening = True
			doc.flags.ignore_permissions = True
			doc.insert()
			doc.submit()
			self.keep(CUSTODY, doc, row["amount"])

	def close_temporary(self) -> None:
		"""Temporary Opening, as the opening documents left it, into Opening Balance Equity."""
		names = [p["reference_name"] for p in self.posted]
		if not names:
			return
		# a record that posts through its own Journal Entry (custody, advances)
		for p in self.posted:
			if frappe.get_meta(p["reference_doctype"]).has_field("journal_entry"):
				entry = frappe.db.get_value(p["reference_doctype"], p["reference_name"], "journal_entry")
				names += [entry] if entry else []
		rows = frappe.get_all(
			"GL Entry",
			{"account": self.plan.temporary, "voucher_no": ("in", names), "is_cancelled": 0},
			["debit", "credit"],
		)
		balance = flt(sum(flt(r.debit) - flt(r.credit) for r in rows), DIGITS)
		if abs(balance) <= ROUNDING:
			return
		temp_side, equity_side = ("credit", "debit") if balance > 0 else ("debit", "credit")
		je = self.journal(
			[
				{"account": self.plan.temporary, temp_side: abs(balance)},
				{"account": self.plan.equity, equity_side: abs(balance)},
			],
			_("Temporary Opening cleared into the owner's equity"),
		)
		self.keep(_("Equity"), je, abs(balance))


def allowed_source(doc, account: str | None) -> bool:
	"""The opening's own documents take their money from Temporary Opening (SP-160)."""
	if not account or not (doc.flags.get("sp_opening") or not doc.docstatus.is_draft()):
		return False
	return frappe.db.get_value("Account", account, "account_name") == TEMPORARY_ACCOUNT


# --- reconciliation --------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def reconcile(name: str) -> dict:
	"""The trial balance on the opening date against the template's, line by line."""
	doc = frappe.get_doc(OPENING, name)
	doc.check_permission("read")
	plan, _digest = _plan(doc)
	actual = {
		r.account: flt(r.net, DIGITS)
		for r in frappe.db.sql(
			"""select account, sum(debit - credit) as net from `tabGL Entry`
			where company = %s and is_cancelled = 0 and posting_date <= %s group by account""",
			(doc.company, plan.on),
			as_dict=True,
		)
	}
	expected: dict = {}
	for t in plan.trial:
		expected[t["account"]] = flt(expected.get(t["account"], 0) + t["net"], DIGITS)
	rows = []
	for account in sorted(set(expected) | {a for a, v in actual.items() if abs(v) > ROUNDING}):
		exp, act = expected.get(account, 0.0), actual.get(account, 0.0)
		rows.append(
			{
				"account": account,
				"expected": exp,
				"actual": act,
				"difference": flt(act - exp, DIGITS),
				"matches": abs(act - exp) <= ROUNDING,
				"in_template": account in expected,
			}
		)
	result = {"rows": rows, "matches": all(r["matches"] for r in rows), "errors": plan.errors}
	doc.db_set("reconcile_json", json.dumps(result, default=str))
	return result
