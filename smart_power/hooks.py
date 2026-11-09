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
app_include_js = ["/assets/smart_power/js/sp_locale.js"]

# The same display formats for print formats and PDFs (SP-22, used by SP-23).
jinja = {
	"methods": [
		"smart_power.sp_core.formatting.time_12h",
		"smart_power.sp_core.formatting.datetime_12h",
	],
}

website_context = {
	"favicon": "/assets/smart_power/images/sp_favicon.png",
	"splash_image": "/assets/smart_power/images/sp_logo.png",
}

# Customer list: gold star for featured customers (SP-31).
doctype_list_js = {"Customer": "public/js/customer_list.js"}

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
sp_rule_modules = ["smart_power.rules.commercial"]

_RULE_EVENTS = {
	"validate": "smart_power.rules.on_doc_event",
	"before_submit": "smart_power.rules.on_doc_event",
}

doc_events = {
	"*": _RULE_EVENTS,
	"SP Rule Setting": {"on_update": "smart_power.rules.clear_cache"},
	# Customer master (SP-31): one customer per mobile.
	"Customer": {"validate": "smart_power.sp_sales.customer.validate"},
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
	"daily": [
		"smart_power.tasks.update_rule_stats",
		"smart_power.tasks.backup_admin_customizations",
	],
}

permission_query_conditions = {
	"SP Task": "smart_power.sp_core.doctype.sp_task.sp_task.get_permission_query_conditions",
}
has_permission = {
	"SP Task": "smart_power.sp_core.doctype.sp_task.sp_task.has_permission",
}

export_python_type_annotations = True
