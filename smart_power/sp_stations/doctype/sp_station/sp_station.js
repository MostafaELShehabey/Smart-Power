// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SP Station (SP-73): the owner chips (sales, execution, collection) and the money chips
// (Agreed · Paid, confirmed only · Remaining · Next due) at the top of the station. The admin
// records a write-off so a station with money left can close financially. The rules are on the
// server (smart_power.sp_stations).
const SP_ST_ADMIN_ROLES = ["SP Admin", "System Manager"];

frappe.ui.form.on("SP Station", {
	refresh(frm) {
		if (frm.is_new()) return;
		sp_station_chips(frm);
		const admin = SP_ST_ADMIN_ROLES.some((r) => frappe.user.has_role(r));
		if (admin && frm.doc.remaining_amount > 0 && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Record Write-off"), () => sp_station_write_off(frm));
		}
		if (frm.doc.project) {
			frm.add_custom_button(__("Project"), () => frappe.set_route("Form", "Project", frm.doc.project), __("View"));
		}
	},
});

function sp_station_chips(frm) {
	const money = (v) => format_currency(v || 0, frm.doc.currency);
	frm.dashboard.clear_headline();
	const due = frm.doc.next_due_date
		? `${money(frm.doc.next_due_amount)} · ${frappe.datetime.str_to_user(frm.doc.next_due_date)}`
		: __("None");
	frm.dashboard.add_indicator(`${__("Agreed")}: ${money(frm.doc.agreed_amount)}`, "blue");
	frm.dashboard.add_indicator(`${__("Paid")}: ${money(frm.doc.paid_amount)}`, "green");
	frm.dashboard.add_indicator(
		`${__("Remaining")}: ${money(frm.doc.remaining_amount)}`,
		frm.doc.remaining_amount > 0 ? "orange" : "green"
	);
	const overdue = frm.doc.next_due_date && frm.doc.next_due_date < frappe.datetime.get_today();
	frm.dashboard.add_indicator(`${__("Next Due")}: ${due}`, overdue ? "red" : "gray");
	const owner = (label, user) => (user ? `${__(label)}: ${frappe.user.full_name(user)}` : "");
	const owners = [
		owner("Sales", frm.doc.sales_owner),
		owner("Execution", frm.doc.execution_owner),
		owner("Collection", frm.doc.collection_owner),
	].filter(Boolean);
	if (owners.length) {
		frm.dashboard.set_headline(owners.map((o) => frappe.utils.escape_html(o)).join(" · "));
	}
}

function sp_station_write_off(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Record Write-off"),
		fields: [
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount"),
				reqd: 1,
				default: frm.doc.remaining_amount,
				description: __("Remaining: {0}", [format_currency(frm.doc.remaining_amount)]),
			},
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		primary_action_label: __("Record Write-off"),
		primary_action: async (values) => {
			await frappe.call({
				method: "smart_power.sp_stations.station.record_write_off",
				args: { station: frm.doc.name, ...values },
				freeze: true,
			});
			dialog.hide();
			frm.reload_doc();
		},
	});
	dialog.show();
}
