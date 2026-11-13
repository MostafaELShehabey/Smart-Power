// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SP Case (SP-46): the rules are on the server (sp_sales/case.py). After the case opens, an
// owner changes only through "Reassign", which asks for a reason and writes the owner history.
const SP_REASSIGN_ROLES = ["SP Admin", "System Manager"];
const SP_OWNERS = [
	{ fieldname: "follow_up_owner", label: "Follow-up Owner" },
	{ fieldname: "quote_creator", label: "Quote Creator" },
	{ fieldname: "requested_by", label: "Requested By" },
];

frappe.ui.form.on("SP Case", {
	refresh(frm) {
		if (frm.is_new() || !SP_REASSIGN_ROLES.some((r) => frappe.user.has_role(r))) return;
		frm.add_custom_button(__("Reassign"), () => sp_reassign_dialog(frm));
	},
});

function sp_reassign_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Reassign"),
		fields: [
			{
				fieldname: "owner_field",
				fieldtype: "Select",
				label: __("Owner"),
				reqd: 1,
				default: "follow_up_owner",
				options: SP_OWNERS.map((o) => ({ value: o.fieldname, label: __(o.label) })),
			},
			{ fieldname: "to_user", fieldtype: "Link", label: __("To"), options: "User" },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		],
		primary_action_label: __("Reassign"),
		primary_action: async (values) => {
			await frappe.call({
				method: "smart_power.sp_sales.case.reassign",
				args: { case: frm.doc.name, ...values },
				freeze: true,
			});
			dialog.hide();
			frm.reload_doc();
		},
	});
	dialog.show();
}
