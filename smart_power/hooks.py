from smart_power.constants import DEV_NAME_PREFIX, MODULE_OWNED_DOCTYPES, PREFIX_OWNED_DOCTYPES, SP_MODULES
from smart_power.sp_core.setup.role_catalogue import LIGHT_ENTRY_ROLES

app_name = "smart_power"
app_title = "Smart Power"
app_publisher = "Smart Power"
app_description = "Smart Power ERP: the custom app for Smart Power (solar energy and power systems)"
app_email = "mostafashraf2120@gmail.com"
app_license = "custom"
app_logo_url = "/assets/smart_power/images/sp_logo.png"
# App shell (SP-37): Smart Power on the apps screen, with its own dock of module-group sidebars
# (smart_power/dock, <module>/sidebar); everyone lands on Home (System Settings default app, SP-38).
app_home = "/desk/smart-power/sp-home"
add_to_apps_screen = [
	{
		"name": app_name,
		"logo": app_logo_url,
		"title": app_title,
		"route": app_home,
		"sequence_id": 0,
	}
]
# each user sees only the module groups they work in (SP-37)
boot_session = [
	"smart_power.shell.apply_to_boot",
	# the doctypes with fields changed by edit-with-reason, and those with rules (SP-44)
	"smart_power.audit.boot",
	"smart_power.rules.boot",
	# the saved-view tabs of the lists (SP-45)
	"smart_power.lists.boot",
	# the owners shown as chips on the record pages (SP-45)
	"smart_power.records.boot",
	# the company the reports open on
	"smart_power.sp_core.services.company.boot",
]

required_apps = ["frappe", "erpnext"]

# Desk shell (SP-22): theme and font. Business logic never lives in client scripts.
app_include_css = ["/assets/smart_power/css/sp_theme.css"]
web_include_css = ["/assets/smart_power/css/sp_theme.css"]
# The login page's Forgot password: email or mobile, a request to the admin (SP-36)
web_include_js = ["/assets/smart_power/js/sp_login.js"]
# Display formats only (12-hour clock with ص/م); stored values are unchanged.
app_include_js = [
	"/assets/smart_power/js/sp_locale.js",
	# Item search by words in any order (SP-29)
	"/assets/smart_power/js/item_search.js",
	# F4 Give a discount, on the case and quote forms (SP-68)
	"/assets/smart_power/js/sp_discount.js",
	# A2 Record a customer payment, on the station and the case (SP-114)
	"/assets/smart_power/js/sp_payment.js",
	# A4 Transfer / deposit, from the Treasury and the holder's profile (SP-117)
	"/assets/smart_power/js/sp_transfer.js",
	# App shell: "+ New" and My Tasks in the dock (SP-37)
	"/assets/smart_power/js/sp_shell.js",
	# Shared form components: edit with reason, rule banner, confirm, pickers, grid (SP-44)
	"/assets/smart_power/js/sp_ui.js",
	# List and record patterns: saved-view tabs, totals, status bar, owner chips (SP-45)
	"/assets/smart_power/js/sp_list.js",
	"/assets/smart_power/js/sp_form.js",
	"/assets/smart_power/js/sp_sales.js",
	# Site photos tagged usable for marketing, on the site log and the station (SP-96, SP-53)
	"/assets/smart_power/js/sp_site.js",
]

# The same display formats for print formats and PDFs (SP-22, used by SP-23).
jinja = {
	"methods": [
		"smart_power.sp_core.formatting.time_12h",
		"smart_power.sp_core.formatting.datetime_12h",
		# Company legal data for templates (SP-25)
		"smart_power.sp_core.services.company.get_company_settings",
		"smart_power.sp_core.services.company.company_logo",
		"smart_power.sp_core.services.company.company_addresses",
		# Printed documents (SP-23)
		"smart_power.sp_core.printing.money",
		"smart_power.sp_core.printing.ar_words",
		"smart_power.sp_core.printing.ar_date",
		"smart_power.sp_core.printing.signature_block",
		# The purchase order to the supplier, by delivery batch (SP-82)
		"smart_power.sp_stock.po_print.po_print",
		"smart_power.sp_stock.transfers.transfer_print",
		"smart_power.sp_stock.site_materials.return_print",
		"smart_power.sp_core.printing.qr",
		"smart_power.sp_core.printing.sp_print_styles",
		"smart_power.sp_core.printing.embed_image",
		# The admin's document text (SP-134, X8)
		"smart_power.sp_core.documents.sp_block",
		"smart_power.sp_core.documents.sp_blocks",
		# The customer quote PDF (SP-62)
		"smart_power.sp_quotes.quote_print.quote_print",
		# the banks' quote formats the admin builds (SP-171)
		"smart_power.sp_quotes.bank_formats.bank_quote_table",
		# The contract PDF (SP-74)
		"smart_power.sp_stations.contract_print.contract_print",
		# The warranty certificate (SP-80)
		"smart_power.sp_stations.close.warranty_print",
		# The customer statement (SP-120)
		"smart_power.sp_finance.balances.customer_statement",
	],
}

# G6 Profile (SP-42) in the user menu
standard_navbar_items = [
	{
		"item_label": "My Profile",
		"item_type": "Route",
		"route": "/app/sp-profile",
		"is_standard": 1,
		"icon": "users",
	},
]

website_context = {
	"favicon": "/assets/smart_power/images/sp_favicon.png",
	"splash_image": "/assets/smart_power/images/sp_logo.png",
}

# Customer list: gold star for featured customers (SP-31).
# Quotation form: New Version / Approve Version (SP-54).
doctype_js = {
	# S2 / TK1 site tasks: check in on site, mark done with the hours (SP-100)
	"Task": "public/js/task.js",
	"Quotation": "public/js/quotation.js",
	# C2 customer record: overview, requests and quotes, calls, stations, documents (SP-50)
	"Customer": "public/js/customer.js",
	# "Convert to request" opens C3 from the lead (SP-51)
	"Lead": "public/js/lead.js",
	# your own transit and custody balances on your profile (SP-26)
	"User": "public/js/user.js",
	# A6 / A6b: source, Reverse, the live balanced check (SP-119)
	"Journal Entry": "public/js/journal_entry.js",
	# internal invoices: print for a bank or the customer, cancel with a reason (SP-125)
	"Sales Invoice": "public/js/sales_invoice.js",
	# a recorded goods receipt is read-only until it is confirmed (SP-84)
	"Purchase Receipt": "public/js/purchase_receipt.js",
	# the stations' split against the order's total (SP-83)
	"Purchase Order": "public/js/purchase_order.js",
	# the supplier's ledger from their record (SP-86)
	"Supplier": "public/js/supplier.js",
	# how far a vehicle is from its oil change (SP-106)
	"Vehicle": "public/js/vehicle.js",
}

doctype_list_js = {
	"Customer": "public/js/customer_list.js",
	# Item list: import from Excel with Arabic headers (SP-29).
	"Item": "public/js/item_list.js",
	# Q1 quotes list: latest versions, all-versions toggle, status indicator (SP-64)
	"Quotation": "public/js/quotation_list.js",
	# P1 purchase orders: the Smart Power status as the indicator (SP-82)
	"Purchase Order": "public/js/purchase_order_list.js",
	# W4 vehicles: the kilometres left to the oil change (SP-106)
	"Vehicle": "public/js/vehicle_list.js",
}

# Drivers and the winch operator land on the field page (SP-34, SP-180).
role_home_page = {role: "sp-field" for role in LIGHT_ENTRY_ROLES}
before_request = [
	"smart_power.sp_core.web.redirect_light_users",
	# a user who must change their password reaches nothing else first (SP-36)
	"smart_power.sp_core.login.guard_first_login",
]
# Login (SP-36): a mobile typed in any form finds the user; a locked account is refused
before_login = ["smart_power.sp_core.login.before_login"]
on_login = ["smart_power.sp_core.login.on_login"]

# Install and migrate
after_install = "smart_power.sp_core.setup.install.after_install"
after_sync = "smart_power.sp_core.setup.install.after_sync"
before_migrate = "smart_power.sp_core.setup.install.before_migrate"
after_migrate = "smart_power.sp_core.setup.install.after_migrate"
setup_wizard_complete = "smart_power.sp_core.setup.locale.apply_locale"

# Fixtures: developer-owned records only (SP-19, SP-164). The admin's own customizations carry
# the "Smart Power Admin" module or a name without the "SP " prefix, so they are never exported.
fixtures = [
	{"dt": dt, "filters": [["module", "in", list(SP_MODULES)]]} for dt in ("Custom Field", "Property Setter")
] + [{"dt": dt, "filters": [["name", "like", DEV_NAME_PREFIX + "%"]]} for dt in ("Role", "Workflow")]
# Role profiles are synced from the role catalogue instead (sp_core/setup/install.py): re-importing
# them as fixtures on every migrate would re-queue a job that rewrites every user's roles.

# A1 Confirmations centre (SP-115): the money DocTypes waiting for the admin, {DocType: module}
# with pending_items / preview / confirm / reject. Transfers, custody and cash box add theirs.
sp_confirmation_sources = {
	"SP Customer Payment": "smart_power.sp_finance.customer_payment",
	"SP Transfer": "smart_power.sp_finance.transfer",  # SP-117
	"SP Custody Settlement": "smart_power.sp_finance.custody",  # SP-122
	"Payment Entry": "smart_power.sp_finance.supplier_payment",  # SP-86
	"SP Cash Box Day": "smart_power.sp_finance.cash_box",  # SP-104: the showroom box's day close
}

# Business rules (SP-128): modules whose @rule functions register at first use.
sp_rule_modules = [
	"smart_power.rules.commercial",
	"smart_power.rules.sales",
	"smart_power.rules.technical",
	"smart_power.rules.finance",
	"smart_power.rules.winch",
]

_RULE_EVENTS = {
	# the rules engine, then the form designer's "required when shown" fields (SP-132)
	"validate": ["smart_power.rules.on_doc_event", "smart_power.sp_core.form_designer.validate_required"],
	"before_submit": "smart_power.rules.on_doc_event",
}

doc_events = {
	# the photos a goods receipt was recorded with stay with it (SP-84)
	"File": {"on_trash": "smart_power.sp_stock.goods_receipt.keep_evidence"},
	# after the contract: "Read-only — now with أميرة" (SP-35)
	"SP Case": {
		"onload": "smart_power.permissions.set_read_only_banner",
		"on_update": [
			# its campaign recounts quotes, won and contracted value (SP-52)
			"smart_power.sp_sales.campaigns.on_case_change",
			# its quotes follow the follow-up owner, system and size in the Q1 list (SP-64)
			"smart_power.sp_sales.quote_list.on_case_change",
		],
	},
	# a lead counts in its campaign (SP-52)
	"Lead": {
		# mobile, duplicates and the follow-up owner (SP-51)
		"validate": "smart_power.sp_sales.leads.validate",
		"after_insert": "smart_power.sp_sales.campaigns.on_lead_change",
		"on_update": "smart_power.sp_sales.campaigns.on_lead_change",
		"on_trash": "smart_power.sp_sales.campaigns.on_lead_change",
	},
	"SP Station": {"onload": "smart_power.permissions.set_read_only_banner"},
	"*": {
		**_RULE_EVENTS,
		# a cancelled source cancels the Journal Entries it posted (SP-113)
		"on_cancel": "smart_power.sp_finance.posting.cancel_postings",
	},
	"SP Rule Setting": {"on_update": "smart_power.rules.clear_cache"},
	# A14 (SP-126): nothing new is recorded into a closed month
	**{
		doctype: {"validate": "smart_power.sp_finance.month_close.guard"}
		for doctype in (
			"SP Customer Payment",
			"SP Transfer",
			"SP Expense",
			"SP Cash Box Day",
			"SP Indirect Split",
		)
	},
	# a showroom sale's cash goes into the showroom box, whatever the Mode of Payment says (SP-102)
	"Sales Invoice": {
		"before_save": "smart_power.sp_sales.showroom_sale.pin_box",
		# an internal invoice is cancelled only by the admin, with a reason (SP-125)
		"before_cancel": "smart_power.sp_finance.invoices.before_cancel",
	},
	# Daily workers (SP-33): a daily wage, no login
	"Employee": {"validate": "smart_power.sp_core.workers.validate"},
	# Customer master (SP-31): one customer per mobile.
	"Customer": {
		"validate": [
			"smart_power.sp_sales.customer.validate",
			# one searchable spelling of its name and mobiles (SP-41)
			"smart_power.sp_core.search_key.set_customer_key",
		]
	},
	# SP-179: turning on an item group's Serial Numbers flag switches its items
	"Item Group": {"on_update": "smart_power.sp_stock.serials.item_group_on_update"},
	# Item catalogue (SP-29): specs that cannot be true are refused.
	"Item": {
		"validate": [
			"smart_power.sp_stock.item.validate",
			# one searchable spelling of its code and names (SP-41)
			"smart_power.sp_core.search_key.set_item_key",
		]
	},
	# Quotation belongs to an SP Case (SP-54)
	"Quotation": {
		"onload": [
			"smart_power.permissions.set_read_only_banner",
			# the case's indicative price, and how far this version is from it (SP-49)
			"smart_power.sp_quotes.indicative.quote_onload",
			# the margin chip: in or out of its range, for its creator and the admin (SP-63)
			"smart_power.rules.sales.margin_onload",
			# Reprice, and honoring the old price, on a version that needs repricing (SP-170)
			"smart_power.sp_quotes.repricing.quote_onload",
			# inverter against motor, depth against pipe length: a banner on a draft (SP-169)
			"smart_power.rules.technical.technical_onload",
		],
		"before_insert": [
			"smart_power.sp_sales.quotation.before_insert",
			# the brand order it starts with: a later reorder changes new quotes only (SP-168)
			"smart_power.sp_quotes.quote_calc.keep_brand_order",
		],
		"before_validate": [
			# what the user was not shown (cost, hidden lines) is kept (SP-35)
			"smart_power.permissions.keep_quote_internals",
			# then the special lines: a commission is cost only (SP-58)
			"smart_power.sp_quotes.special_lines.before_validate",
			"smart_power.sp_quotes.discounts.check_locked_lines",
		],
		"after_insert": [
			"smart_power.sp_sales.quotation.after_insert",
			# the Q1 list: the newest version of each chain (SP-64)
			"smart_power.sp_sales.quote_list.on_quote_change",
		],
		"validate": [
			"smart_power.sp_sales.quotation.validate",
			# the Q1 list: follow-up owner, system and size from the case (SP-64)
			"smart_power.sp_sales.quote_list.set_list_fields",
			# each draft line's price age, for the clock on stale lines (SP-63)
			"smart_power.sp_quotes.price_age.set_line_ages",
			# one installment plan per active template, after the totals and the cost (SP-60)
			"smart_power.sp_quotes.payment_plans.set_quote_plans",
			# the total in Arabic words, a field any print format can show (SP-171)
			"smart_power.sp_quotes.bank_formats.set_total_in_words",
		],
		"before_cancel": "smart_power.sp_sales.quotation.before_cancel",
		"before_update_after_submit": "smart_power.sp_sales.quotation.before_update_after_submit",
		"on_update": [
			"smart_power.sp_sales.quotation.on_update",
			# every discount is listed in the review centre (SP-129)
			"smart_power.sp_core.review_centre.list_quote_discount",
		],
		"on_submit": [
			"smart_power.sp_sales.quotation.on_update",
			"smart_power.sp_sales.campaigns.on_quote_change",  # SP-52
		],
		"on_cancel": [
			"smart_power.sp_sales.campaigns.on_quote_change",
			"smart_power.sp_sales.quote_list.on_quote_change",
		],
		"on_trash": "smart_power.sp_sales.quote_list.on_quote_change",
	},
	# Purchase orders (SP-82): destination, delivery batches and status
	"Purchase Order": {
		"before_validate": "smart_power.sp_stock.purchase_orders.before_validate",
		"validate": [
			"smart_power.sp_stock.purchase_orders.validate",
			# one order shared between stations by amount (SP-83)
			"smart_power.sp_stock.shared_purchase.validate_order",
		],
		"on_submit": "smart_power.sp_stock.purchase_orders.on_change",
		"on_cancel": "smart_power.sp_stock.purchase_orders.on_change",
	},
	# W4: the center and the next oil change (SP-106)
	"Vehicle": {
		"before_validate": "smart_power.sp_winch.vehicles.before_validate",
		"validate": "smart_power.sp_winch.vehicles.validate",
	},
	"Purchase Receipt": {
		# a receiver's draft waits for the technical office: no edits, no submit until confirmed (SP-84)
		"validate": "smart_power.sp_stock.goods_receipt.validate",
		"before_submit": "smart_power.sp_stock.goods_receipt.before_submit",
		# a shared order's goods come back to the store before the receipt is cancelled (SP-83)
		"before_cancel": "smart_power.sp_stock.shared_purchase.before_cancel_receipt",
		"on_submit": "smart_power.sp_stock.purchase_orders.on_receipt_change",
		"on_cancel": "smart_power.sp_stock.purchase_orders.on_receipt_change",
	},
	# The contract (SP-74): one Sales Order per case; the station's money follows it
	"Sales Order": {
		"validate": "smart_power.sp_stations.contract.validate_order",
		"on_update": "smart_power.sp_stations.contract.on_order_change",
		# signing needs the contract's periods and keeps its template version (SP-75)
		"before_submit": "smart_power.sp_stations.contract.before_submit_order",
		"before_update_after_submit": "smart_power.sp_stations.contract.before_update_after_submit_order",
		"on_submit": [
			"smart_power.sp_stations.contract.on_order_change",
			# the contract's postal cheques join the register (SP-118)
			"smart_power.sp_finance.cheques.from_contract",
			# financed by the Agri Bank: the admin records the customer's advance (SP-121)
			"smart_power.sp_finance.advances.on_contract",
		],
		"on_cancel": "smart_power.sp_stations.contract.on_order_change",
		# a plan's cheque joins the register when its number is filled in (SP-60)
		"on_update_after_submit": "smart_power.sp_finance.cheques.from_contract",
	},
	# A posted entry is reversed, never cancelled; one without a source is a manual entry (SP-119)
	"Journal Entry": {
		"before_cancel": "smart_power.sp_finance.journal.before_cancel",
		"on_submit": "smart_power.sp_finance.journal.on_submit",
	},
	# A confirmed (or reversed) customer payment refreshes its station's money (SP-73)
	"Payment Entry": {
		# a confirmed deposit makes the contract and the station (SP-175)
		# a supplier payment leaves only through the admin's confirmation (SP-86)
		"validate": "smart_power.sp_finance.supplier_payment.validate",
		"before_submit": [
			"smart_power.sp_finance.supplier_payment.before_submit",
			"smart_power.sp_stations.deposit.before_submit",
		],
		"on_submit": [
			"smart_power.sp_stations.money.on_payment",
			"smart_power.sp_stations.deposit.on_submit",
			"smart_power.sp_finance.supplier_payment.on_change",
		],
		"on_cancel": [
			"smart_power.sp_stations.money.on_payment",
			"smart_power.sp_finance.supplier_payment.on_change",
		],
	},
	# Ticked on the User form: the person's transit / custody account is made (SP-26)
	# a failed sign-in counts towards the lock (SP-36)
	"Activity Log": {"after_insert": "smart_power.sp_core.login.on_failed_login"},
	"User": {
		# the mobile in its local form, for mobile login (SP-36)
		# a password given by the admin is changed at the first login (SP-36); before Frappe's
		# validate, which clears the new password
		"before_validate": "smart_power.sp_core.login.set_must_change",
		"validate": "smart_power.sp_core.login.validate_user",
		"on_update": "smart_power.sp_finance.accounts.on_user_update",
	},
	# Price list (SP-30): every price has a date and buying prices a supplier.
	"Item Price": {"validate": "smart_power.sp_stock.prices.validate_item_price"},
	# Warehouses by location (SP-28): one site warehouse per station.
	"Warehouse": {"validate": "smart_power.sp_stock.warehouses.validate_warehouse"},
	**{
		dt: {
			"before_insert": "smart_power.events.customization.tag_admin_owned",
			"validate": "smart_power.events.customization.tag_admin_owned",
		}
		for dt in MODULE_OWNED_DOCTYPES
	},
	**{
		dt: {"before_insert": "smart_power.events.customization.guard_dev_names"}
		for dt in PREFIX_OWNED_DOCTYPES
	},
}

scheduler_events = {
	# a snoozed task whose time has passed comes back to the inbox (SP-39)
	"hourly": ["smart_power.sp_core.inbox.unsnooze"],
	"cron": {
		# 24 h quote clock: amber and overdue alerts every 15 minutes (SP-48)
		"*/15 * * * *": ["smart_power.sp_sales.quote_alerts.check_quote_clock"],  # sp-allow-number: cron
	},
	"daily": [
		# campaign results, for what changed outside a doc event (SP-52)
		"smart_power.sp_sales.campaigns.refresh_active",
		# sent quote versions past Valid Till become Expired (SP-54)
		"smart_power.sp_sales.quotation.expire_quotes",
		# expired or price-changed quotes before the deposit: Needs repricing, with alerts (SP-170)
		"smart_power.sp_quotes.repricing.check_quotes",
		# open cases with no action for Case Inactivity Alert days: the owner and the admin (SP-71)
		"smart_power.sp_sales.followup.check_inactivity",
		# cash held too long in a transit account: the holder and the admin, daily (SP-116)
		"smart_power.sp_finance.transit.check_cash_held",
		# postal cheques due soon: Due, with alerts (SP-118)
		"smart_power.sp_finance.cheques.check_due",
		# station hand-overs from today: the new owners, before the instalment alerts (SP-79)
		"smart_power.sp_stations.reassign.apply_scheduled",
		# contract instalments: allocated, Overdue, due and overdue alerts once (SP-81)
		"smart_power.sp_stations.installments.update_installments",
		# a vehicle close to its oil change: its driver and the winch manager (SP-106)
		"smart_power.sp_winch.vehicles.check_oil_due",
		# field entries past their window show Locked; those locking next are announced (SP-109)
		"smart_power.sp_winch.field_lock.lock_entries",
		# the field review flags that change after the save: balances, held cash (SP-110)
		"smart_power.sp_winch.review.refresh_flags",
		# winch jobs unpaid past the debt age: the winch manager and the admin, once (SP-112)
		"smart_power.sp_winch.receivables.check_old_debts",
		# showroom items at or under their reorder level: the showroom store keepers (SP-87)
		"smart_power.sp_stock.showroom_stock.check_showroom_stock",
		# the scheduled stock counts: a sheet and a task for the store keeper, once a week or month (SP-94)
		"smart_power.sp_stock.stock_count.create_scheduled_counts",
		# on the 1st: the consignment reconciliation sheet for the month just closed (SP-93)
		"smart_power.sp_stock.consignment_reconciliation.create_monthly",
		# qualification documents at a reminder mark: the compliance officer and the admin, once (SP-101)
		"smart_power.sp_stations.compliance.expiry_reminders",
		"smart_power.tasks.update_rule_stats",
		"smart_power.tasks.backup_admin_customizations",
	],
}

permission_query_conditions = {
	# a user reads the guides of their own profiles; the admin reads them all (SP-162)
	"SP User Guide": "smart_power.sp_core.guides.query_conditions",
	# who asked to reopen a day sees their own request (SP-109)
	"SP Reopen Request": "smart_power.sp_winch.field_lock.query_conditions",
	# an operator sees their own field entries (SP-108)
	"SP Field Entry": "smart_power.sp_winch.field_entry.query_conditions",
	# a marketing agent sees her own campaigns (SP-52)
	"SP Campaign": "smart_power.sp_sales.campaigns.query_conditions",
	# leads: one's own, made, owned or to follow up (SP-51)
	"Lead": "smart_power.sp_sales.leads.query_conditions",
	"SP Task": [
		"smart_power.sp_core.doctype.sp_task.sp_task.get_permission_query_conditions",
		"smart_power.sp_core.row_rules.query_conditions",
	],
	# Buying prices (List Price, P1 Cost) for cost roles only (SP-35).
	"Item Price": "smart_power.permissions.item_price_query_conditions",
	# A case is seen by its owners; كاميليا and the admin see all (SP-35, SP-46).
	"SP Case": [
		"smart_power.permissions.case_query_conditions",
		"smart_power.sp_core.row_rules.query_conditions",
	],
	# featured customers for all, the rest for their owners (SP-50)
	"Customer": "smart_power.permissions.customer_query_conditions",
	# a case's quotes follow the case (SP-35)
	"Quotation": "smart_power.permissions.quote_query_conditions",
	# money accounts: others see only their own transit and custody (SP-26)
	"Account": "smart_power.sp_finance.accounts.account_query_conditions",
	"GL Entry": "smart_power.sp_finance.accounts.gl_query_conditions",
	# a collection officer sees only the stations they collect (SP-120)
	"SP Station": [
		"smart_power.permissions.station_query_conditions",
		"smart_power.sp_core.row_rules.query_conditions",
	],
	# a customer payment: its recorder, its collector and the admin (SP-35)
	"Payment Entry": "smart_power.permissions.payment_query_conditions",
	"SP Customer Payment": "smart_power.permissions.customer_payment_query_conditions",
	# a custody holder sees only their own custody and settlements (SP-122)
	"SP Custody": "smart_power.sp_finance.custody.custody_query",
	"SP Custody Settlement": "smart_power.sp_finance.custody.settlement_query",
	"SP Service Ticket": "smart_power.sp_core.row_rules.query_conditions",  # SP-131
}
has_permission = {
	"SP User Guide": "smart_power.sp_core.guides.has_permission",
	"SP Field Entry": "smart_power.sp_winch.field_entry.has_permission",
	"SP Campaign": "smart_power.sp_sales.campaigns.has_permission",
	"Lead": "smart_power.sp_sales.leads.has_permission",
	"SP Task": [
		"smart_power.sp_core.doctype.sp_task.sp_task.has_permission",
		"smart_power.sp_core.row_rules.has_permission",
	],
	"Item Price": "smart_power.permissions.item_price_has_permission",
	"SP Case": [
		"smart_power.permissions.case_has_permission",
		"smart_power.sp_core.row_rules.has_permission",
	],
	"Customer": "smart_power.permissions.customer_has_permission",
	"Quotation": "smart_power.permissions.quote_has_permission",
	"Account": "smart_power.sp_finance.accounts.account_has_permission",
	"Journal Entry": "smart_power.sp_finance.journal.has_permission",
	"SP Station": [
		"smart_power.permissions.station_has_permission",
		"smart_power.sp_core.row_rules.has_permission",
	],
	"Payment Entry": "smart_power.permissions.payment_has_permission",
	"SP Customer Payment": "smart_power.permissions.customer_payment_has_permission",
	"SP Custody": "smart_power.sp_finance.custody.has_permission",
	"SP Custody Settlement": "smart_power.sp_finance.custody.has_permission",
	"SP Service Ticket": "smart_power.sp_core.row_rules.has_permission",  # SP-131
}

# the quote's cost and hidden lines leave the server only for its creator and the admin (SP-35)
extend_doctype_class = {
	"Quotation": ["smart_power.sp_sales.quotation_class.SPQuotation"],
	# purchase orders keep their Smart Power status with every ERPNext status change (SP-82)
	"Purchase Order": ["smart_power.sp_stock.purchase_orders.PurchaseOrderStatus"],
}

# ERPNext's "Update Items" is refused on a case's sent quote (SP-61)
override_whitelisted_methods = {
	# a changed password clears Must Change Password (SP-36)
	"frappe.core.doctype.user.user.update_password": "smart_power.sp_core.login.update_password",
	# Forgot password goes to the admin, never an email (SP-36)
	"frappe.core.doctype.user.user.reset_password": "smart_power.sp_core.login.request_password_reset",
	"erpnext.controllers.accounts_controller.update_child_qty_rate": (
		"smart_power.sp_sales.quotation.update_child_qty_rate"
	),
}

export_python_type_annotations = True
