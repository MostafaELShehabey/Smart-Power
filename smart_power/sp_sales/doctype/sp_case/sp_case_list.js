// SP Case list (SP-35): marketing sees its own leads, and the "Mine" filter stays on.
// The server's row rule (smart_power.permissions.case_query_conditions) already limits what the
// list can hold; this keeps the marketing list on the leads she brought in.
const SP_CASE_SEES_ALL = ["SP Admin", "System Manager", "SP Followup All"];

function sp_case_mine_locked() {
	return (
		frappe.user.has_role("SP Marketing Agent") &&
		!SP_CASE_SEES_ALL.some((r) => frappe.user.has_role(r))
	);
}

function sp_case_lock_mine(listview) {
	const me = frappe.session.user;
	const filters = listview.filter_area.get();
	const mine = filters.some(([, field, op, value]) => field === "requested_by" && op === "=" && value === me);
	if (!mine) {
		listview.filter_area.remove("requested_by");
		listview.filter_area.add([["SP Case", "requested_by", "=", me]]);
	}
	// the filter cannot be cleared: the clear button is hidden (and a removed filter comes back)
	listview.$page.find(".filter-x-button").hide();
}

frappe.listview_settings["SP Case"] = Object.assign(frappe.listview_settings["SP Case"] || {}, {
	onload(listview) {
		if (!sp_case_mine_locked()) return;
		listview.page.set_title(__("My Leads"));
		sp_case_lock_mine(listview);
	},
	refresh(listview) {
		if (sp_case_mine_locked()) sp_case_lock_mine(listview);
	},
});
