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
		// read-only for sales after the contract (SP-35); the banner leads the owners line
		if (frm.doc.__onload?.sp_read_only) frm.disable_form();
		sp_station_chips(frm);
		// photos of the finished station, tagged usable for marketing (SP-53)
		smart_power.site_photos(frm, "photos_html", "");
		const admin = SP_ST_ADMIN_ROLES.some((r) => frappe.user.has_role(r));
		if (frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Record Payment"), () =>
				smart_power.record_payment_dialog({ station: frm.doc.name }, () => frm.reload_doc())
			);
		}
		// financed by the Agri Bank: the customer's own share is advanced and tracked apart (SP-121)
		const bank_financing = admin || frappe.user.has_role("SP Bank Financing");
		if (bank_financing && frm.doc.financing_type === "Financing Type-AGRI" && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Agri Bank Advance"), () =>
				frappe.new_doc("SP Customer Advance", { station: frm.doc.name })
			);
		}
		if (admin && frm.doc.remaining_amount > 0 && frm.doc.status !== "Cancelled") {
			frm.add_custom_button(__("Record Write-off"), () => sp_station_write_off(frm));
		}
		if (frm.doc.sales_order) {
			frm.add_custom_button(__("Contract"), () => frappe.set_route("Form", "Sales Order", frm.doc.sales_order), __("View"));
		} else if (frm.doc.case) {
			sp_station_contract_button(frm);
		}
		if (frm.doc.project) {
			frm.add_custom_button(__("Project"), () => frappe.set_route("Form", "Project", frm.doc.project), __("View"));
		}
		// PR1 programming and the operation date, one per system (SP-97)
		if (frm.doc.status !== "Cancelled" && frappe.model.can_create("SP Commissioning")) {
			frm.add_custom_button(
				__("Commissioning"),
				() => frappe.new_doc("SP Commissioning", { station: frm.doc.name }),
				__("Create")
			);
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
	if (frm.doc.pending_amount > 0) {
		frm.dashboard.add_indicator(`${__("Pending")}: ${money(frm.doc.pending_amount)}`, "yellow");
	}
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
	const parts = owners.map((o) => frappe.utils.escape_html(o));
	const read_only = frm.doc.__onload?.sp_read_only;
	if (read_only) parts.unshift(`<b>${frappe.utils.escape_html(read_only)}</b>`);
	if (parts.length) frm.dashboard.set_headline(parts.join(" · "), read_only ? "orange" : undefined);
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

// The contract (SP-74) when the station was opened before it: made from the case's approved version.
function sp_station_contract_button(frm) {
	frm.add_custom_button(__("Make Contract"), () =>
		frappe.confirm(__("Make the contract (Sales Order) from the case's approved version?"), async () => {
			const { message: result } = await frappe.call({
				method: "smart_power.sp_stations.contract.make_contract",
				args: { case: frm.doc.case },
				freeze: true,
			});
			frappe.set_route("Form", "Sales Order", result.sales_order);
		})
	);
}
