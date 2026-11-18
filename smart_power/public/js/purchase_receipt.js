// A receipt recorded on the Receive Goods page (SP-84) waits for its confirmer: nobody edits or
// submits it from the form, and the server refuses both.
frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0 || !frm.doc.sp_receipt_status) return;
		frm.disable_form();
		frm.page.clear_primary_action();
		frm.dashboard.clear_comment();
	},
});
