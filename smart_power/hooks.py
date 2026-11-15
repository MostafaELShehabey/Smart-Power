from smart_power.constants import DEV_NAME_PREFIX, MODULE_OWNED_DOCTYPES, PREFIX_OWNED_DOCTYPES, SP_MODULES
from smart_power.sp_core.setup.role_catalogue import LIGHT_ENTRY_ROLES

app_name = "smart_power"
app_title = "Smart Power"
app_publisher = "Smart Power"
app_description = "Smart Power ERP: the custom app for Smart Power (solar energy and power systems)"
app_email = "mostafashraf2120@gmail.com"
app_license = "custom"
app_logo_url = "/assets/smart_power/images/sp_logo.png"

required_apps = ["frappe", "erpnext"]

# Desk shell (SP-22): theme and font. Business logic never lives in client scripts.
app_include_css = ["/assets/smart_power/css/sp_theme.css"]
web_include_css = ["/assets/smart_power/css/sp_theme.css"]
# Display formats only (12-hour clock with ص/م); stored values are unchanged.
app_include_js = [
	"/assets/smart_power/js/sp_locale.js",
	# Item search by words in any order (SP-29)
	"/assets/smart_power/js/item_search.js",
	# F4 Give a discount, on the case and quote forms (SP-68)
	"/assets/smart_power/js/sp_discount.js",
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
		"smart_power.sp_core.printing.qr",
		"smart_power.sp_core.printing.sp_print_styles",
		"smart_power.sp_core.printing.embed_image",
		# The admin's document text (SP-134, X8)
		"smart_power.sp_core.documents.sp_block",
		"smart_power.sp_core.documents.sp_blocks",
		# The customer quote PDF (SP-62)
		"smart_power.sp_quotes.quote_print.quote_print",
		# The contract PDF (SP-74)
		"smart_power.sp_stations.contract_print.contract_print",
	],
}

website_context = {
	"favicon": "/assets/smart_power/images/sp_favicon.png",
	"splash_image": "/assets/smart_power/images/sp_logo.png",
}

# Customer list: gold star for featured customers (SP-31).
# Quotation form: New Version / Approve Version (SP-54).
doctype_js = {"Quotation": "public/js/quotation.js"}

doctype_list_js = {
	"Customer": "public/js/customer_list.js",
	# Item list: import from Excel with Arabic headers (SP-29).
	"Item": "public/js/item_list.js",
}

# Drivers and the winch operator land on the field page (SP-34, SP-180).
role_home_page = {role: "sp-field" for role in LIGHT_ENTRY_ROLES}
before_request = ["smart_power.sp_core.web.redirect_light_users"]

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

# Business rules (SP-128): modules whose @rule functions register at first use.
sp_rule_modules = ["smart_power.rules.commercial", "smart_power.rules.sales"]

_RULE_EVENTS = {
	"validate": "smart_power.rules.on_doc_event",
	"before_submit": "smart_power.rules.on_doc_event",
}

doc_events = {
	"*": {
		**_RULE_EVENTS,
		# a cancelled source cancels the Journal Entries it posted (SP-113)
		"on_cancel": "smart_power.sp_finance.posting.cancel_postings",
	},
	"SP Rule Setting": {"on_update": "smart_power.rules.clear_cache"},
	# Customer master (SP-31): one customer per mobile.
	"Customer": {"validate": "smart_power.sp_sales.customer.validate"},
	# Item catalogue (SP-29): specs that cannot be true are refused.
	"Item": {"validate": "smart_power.sp_stock.item.validate"},
	# Quotation belongs to an SP Case (SP-54)
	"Quotation": {
		"before_insert": "smart_power.sp_sales.quotation.before_insert",
		"before_validate": "smart_power.sp_quotes.discounts.check_locked_lines",
		"after_insert": "smart_power.sp_sales.quotation.after_insert",
		"validate": "smart_power.sp_sales.quotation.validate",
		"before_cancel": "smart_power.sp_sales.quotation.before_cancel",
		"before_update_after_submit": "smart_power.sp_sales.quotation.before_update_after_submit",
		"on_update": [
			"smart_power.sp_sales.quotation.on_update",
			# every discount is listed in the review centre (SP-129)
			"smart_power.sp_core.review_centre.list_quote_discount",
		],
		"on_submit": "smart_power.sp_sales.quotation.on_update",
	},
	# The contract (SP-74): one Sales Order per case; the station's money follows it
	"Sales Order": {
		"validate": "smart_power.sp_stations.contract.validate_order",
		"on_update": "smart_power.sp_stations.contract.on_order_change",
		"on_submit": "smart_power.sp_stations.contract.on_order_change",
		"on_cancel": "smart_power.sp_stations.contract.on_order_change",
	},
	# A confirmed (or reversed) customer payment refreshes its station's money (SP-73)
	"Payment Entry": {
		# a confirmed deposit makes the contract and the station (SP-175)
		"before_submit": "smart_power.sp_stations.deposit.before_submit",
		"on_submit": [
			"smart_power.sp_stations.money.on_payment",
			"smart_power.sp_stations.deposit.on_submit",
		],
		"on_cancel": "smart_power.sp_stations.money.on_payment",
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
	"cron": {
		# 24 h quote clock: amber and overdue alerts every 15 minutes (SP-48)
		"*/15 * * * *": ["smart_power.sp_sales.quote_alerts.check_quote_clock"],  # sp-allow-number: cron
	},
	"daily": [
		# sent quote versions past Valid Till become Expired (SP-54)
		"smart_power.sp_sales.quotation.expire_quotes",
		"smart_power.tasks.update_rule_stats",
		"smart_power.tasks.backup_admin_customizations",
	],
}

permission_query_conditions = {
	"SP Task": "smart_power.sp_core.doctype.sp_task.sp_task.get_permission_query_conditions",
	# Buying prices (List Price, P1 Cost) for cost roles only (SP-35).
	"Item Price": "smart_power.permissions.item_price_query_conditions",
	# A case is seen by its owners; كاميليا and the admin see all (SP-35, SP-46).
	"SP Case": "smart_power.permissions.case_query_conditions",
}
has_permission = {
	"SP Task": "smart_power.sp_core.doctype.sp_task.sp_task.has_permission",
	"Item Price": "smart_power.permissions.item_price_has_permission",
	"SP Case": "smart_power.permissions.case_has_permission",
}

# ERPNext's "Update Items" is refused on a case's sent quote (SP-61)
override_whitelisted_methods = {
	"erpnext.controllers.accounts_controller.update_child_qty_rate": (
		"smart_power.sp_sales.quotation.update_child_qty_rate"
	),
}

export_python_type_annotations = True
