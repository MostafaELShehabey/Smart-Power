// Internal invoices (SP-125): numbered SINV-YYYY-####, printed only for a bank or the customer (the
// admin or the accountant; each print is logged), cancelled only by the admin with a reason. The
// rules are on the server (smart_power.sp_finance.invoices).
const SP_INV_API = "smart_power.sp_finance.invoices";

frappe.ui.form.on("Sales Invoice", {
	async refresh(frm) {
		if (!frm.doc.name.startsWith("SINV-") || frm.doc.docstatus !== 1) return;
		const roles = frappe.user_roles;
		const admin = ["SP Admin", "System Manager"].some((r) => roles.includes(r));
		const printer = admin || roles.includes("SP Accountant");
		if (printer) {
			frm.add_custom_button(__("Print for a Bank or Customer"), () => sp_inv_print(frm));
			sp_inv_log(frm);
		}
		if (admin) frm.add_custom_button(__("Cancel with Reason"), () => sp_inv_cancel(frm));
	},
});

function sp_inv_print(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Print {0}", [frm.doc.name]),
		fields: [
			{ fieldname: "for_kind", fieldtype: "Select", label: __("Printed for"), options: [
				{ value: "Bank", label: __("Bank") },
				{ value: "Customer", label: __("Customer") },
			], default: "Bank", reqd: 1 },
			{ fieldname: "for_whom", fieldtype: "Data", label: __("Which bank"), depends_on: "eval:doc.for_kind==='Bank'", mandatory_depends_on: "eval:doc.for_kind==='Bank'" },
		],
		primary_action_label: __("Print"),
		primary_action: async (v) => {
			await frappe.call({ method: `${SP_INV_API}.print_invoice`, args: { name: frm.doc.name, ...v }, freeze: true });
			dialog.hide();
			window.open(frappe.urllib.get_full_url(`/printview?doctype=${encodeURIComponent(frm.doctype)}&name=${encodeURIComponent(frm.doc.name)}&trigger_print=1`));
			sp_inv_log(frm);
		},
	});
	dialog.show();
}

async function sp_inv_log(frm) {
	const { message: rows } = await frappe.call(`${SP_INV_API}.print_log`, { name: frm.doc.name });
	if (!rows || !rows.length) return;
	const esc = frappe.utils.escape_html;
	const text = rows
		.map((r) => `${esc(frappe.datetime.str_to_user(r.at))} · ${esc((frappe.user_info(r.user) || {}).fullname || r.user)} · ${esc(__(r.for_kind))}: ${esc(r.whom || "")}`)
		.join("<br>");
	frm.set_intro(`${esc(__("Printed"))}:<br>${text}`, "blue");
}

function sp_inv_cancel(frm) {
	frappe.prompt(
		{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
		async ({ reason }) => {
			await frappe.call({ method: `${SP_INV_API}.cancel_invoice`, args: { name: frm.doc.name, reason }, freeze: true });
			frm.reload_doc();
		},
		__("Cancel {0}", [frm.doc.name]),
		__("Cancel the Invoice")
	);
}
