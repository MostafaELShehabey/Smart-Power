"""SP-75: signed contracts keep the contract template they print with today, and the starting
template's period clauses get the contract's days (only if the admin has not changed them)."""

import frappe

from smart_power.sp_core.documents import CONTRACT_BLOCKS, TEMPLATE, published

# the SP-74 starting text, before the days were on the contract
OLD_PERIODS = {
	"supply_period": "<p>يتم التوريد خلال المدة المتفق عليها من تاريخ استلام الدفعة المقدمة.</p>",
	"installation_period": "<p>يتم التركيب خلال المدة المتفق عليها من تاريخ اكتمال التوريد وتجهيز الموقع.</p>",
}


def execute():
	from frappe.utils.fixtures import sync_fixtures

	sync_fixtures("smart_power")  # the new fields come with the fixtures, synced after patches
	current = published("Contract")
	if not current:
		return
	for name in frappe.get_all(
		"Sales Order",
		{"docstatus": 1, "sp_case": ("is", "set"), "sp_contract_template": ("is", "not set")},
		pluck="name",
	):
		frappe.db.set_value("Sales Order", name, "sp_contract_template", current, update_modified=False)

	template = frappe.get_doc(TEMPLATE, current)
	bodies = {row.block_key: row.body for row in template.blocks}
	if any(bodies.get(key) != text for key, text in OLD_PERIODS.items()):
		return  # the admin's own text: they add the days themselves
	new_text = {key: body for key, _title, body in CONTRACT_BLOCKS if key in OLD_PERIODS}
	copy = frappe.copy_doc(template, ignore_no_copy=False)
	copy.previous_version = template.name
	for row in copy.blocks:
		row.body = new_text.get(row.block_key, row.body)
	copy.insert(ignore_permissions=True)
	copy.publish_now()
