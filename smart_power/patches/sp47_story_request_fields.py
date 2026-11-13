"""SP-47: the story's request fields replace the earlier proposal (built while Jira was
unreachable), on each system type whose fields the admin has not changed."""

import json

import frappe

from smart_power.sp_core.setup.seed import defaults
from smart_power.sp_sales.quote_request import LIST_VALUE, META_KEY, SYSTEM_TYPE_LIST

# What sp47_request_fields seeded before the story was read.
EARLIER_PROPOSAL = {
	"PUMP": [
		{
			"fieldname": "well_depth_m",
			"label": "Well Depth (m)",
			"label_ar": "عمق البئر (متر)",
			"fieldtype": "Float",
			"reqd": 0,
		},
		{
			"fieldname": "head_m",
			"label": "Head (m)",
			"label_ar": "الرفع (متر)",
			"fieldtype": "Float",
			"reqd": 0,
		},
		{
			"fieldname": "flow_m3h",
			"label": "Flow (m³/h)",
			"label_ar": "التصرف (م³/ساعة)",
			"fieldtype": "Float",
			"reqd": 0,
		},
		{
			"fieldname": "motor_hp",
			"label": "Motor (HP)",
			"label_ar": "قدرة الموتور (حصان)",
			"fieldtype": "Float",
			"reqd": 0,
		},
	],
	"OFFGRID": [
		{
			"fieldname": "daily_load_kwh",
			"label": "Daily Load (kWh)",
			"label_ar": "الحمل اليومي (كيلووات ساعة)",
			"fieldtype": "Float",
			"reqd": 0,
		},
		{
			"fieldname": "backup_hours",
			"label": "Backup Hours",
			"label_ar": "ساعات التشغيل الاحتياطي",
			"fieldtype": "Float",
			"reqd": 0,
		},
	],
	"ONGRID": [
		{
			"fieldname": "monthly_kwh",
			"label": "Monthly Consumption (kWh)",
			"label_ar": "الاستهلاك الشهري (كيلووات ساعة)",
			"fieldtype": "Float",
			"reqd": 0,
		},
		{
			"fieldname": "roof_area_m2",
			"label": "Roof Area (m²)",
			"label_ar": "مساحة السطح (م²)",
			"fieldtype": "Float",
			"reqd": 0,
		},
	],
	"HYBRID": [
		{
			"fieldname": "daily_load_kwh",
			"label": "Daily Load (kWh)",
			"label_ar": "الحمل اليومي (كيلووات ساعة)",
			"fieldtype": "Float",
			"reqd": 0,
		},
		{
			"fieldname": "monthly_kwh",
			"label": "Monthly Consumption (kWh)",
			"label_ar": "الاستهلاك الشهري (كيلووات ساعة)",
			"fieldtype": "Float",
			"reqd": 0,
		},
	],
}


def execute():
	story = defaults()[META_KEY]
	for code, fields in story.items():
		if code.startswith("_"):
			continue
		name = frappe.db.get_value(LIST_VALUE, {"list_name": SYSTEM_TYPE_LIST, "code": code})
		if not name:
			continue
		raw = frappe.db.get_value(LIST_VALUE, name, "meta_json")
		meta = (raw if isinstance(raw, dict) else json.loads(raw)) if raw else {}
		current = meta.get(META_KEY)
		if current is None or current == EARLIER_PROPOSAL.get(code):
			meta[META_KEY] = fields
			frappe.db.set_value(LIST_VALUE, name, "meta_json", json.dumps(meta, ensure_ascii=False))
