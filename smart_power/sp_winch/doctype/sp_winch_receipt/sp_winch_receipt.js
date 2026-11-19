// Winch receipt (SP-112): money collected from a customer, allocated to the jobs it pays.
// Left without jobs it is allocated oldest first on save; the rules are on the server
// (smart_power.sp_winch.receipts).
const SP_WINCH_RECEIPT_API = "smart_power.sp_winch.receipts";

frappe.ui.form.on("SP Winch Receipt", {
	setup(frm) {
		frm.set_query("to_account", () => ({
			query: "smart_power.sp_winch.field_entry.official_account_query",
		}));
		frm.set_query("method", () => ({ filters: { list_name: "Payment Method", is_active: 1 } }));
		frm.set_query("job", "allocations", () => ({
			query: `${SP_WINCH_RECEIPT_API}.open_jobs_query`,
			filters: { customer: frm.doc.customer },
		}));
	},
	onload(frm) {
		if (frm.is_new() && !frm.doc.holder) frm.set_value("holder", frappe.session.user);
		if (frm.is_new() && !frm.doc.method) frm.set_value("method", "Payment Method-CASH");
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Allocate Oldest First"), () => sp_allocate_oldest_first(frm));
		}
	},
	customer(frm) {
		frm.clear_table("allocations");
		frm.refresh_field("allocations");
	},
});

async function sp_allocate_oldest_first(frm) {
	if (!frm.doc.customer || !frm.doc.amount) {
		frappe.msgprint(__("Choose the customer and enter the amount first."));
		return;
	}
	const { message: rows } = await frappe.call({
		method: `${SP_WINCH_RECEIPT_API}.suggest`,
		args: { customer: frm.doc.customer, amount: frm.doc.amount, receipt: frm.is_new() ? null : frm.doc.name },
	});
	frm.clear_table("allocations");
	(rows || []).forEach((row) => frm.add_child("allocations", row));
	frm.refresh_field("allocations");
	if (!(rows || []).length) {
		frappe.show_alert({ message: __("This customer has no open jobs."), indicator: "orange" });
	}
}
