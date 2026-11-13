// Quotation (SP-54): versions of a case's quote. The rules are on the server
// (smart_power.sp_sales.quotation); this only adds the buttons and the version note.
frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (!frm.doc.sp_case || frm.is_new()) return;
		const API = "smart_power.sp_sales.quotation";
		const note = frm.doc.sp_is_approved
			? __("Version {0} of case {1}: the approved version.", [frm.doc.sp_version, frm.doc.sp_case])
			: __("Version {0} of case {1}.", [frm.doc.sp_version, frm.doc.sp_case]);
		frm.set_intro(note, frm.doc.sp_is_approved ? "green" : "blue");

		frm.add_custom_button(__("New Version"), async () => {
			const { message: name } = await frappe.call({
				method: `${API}.new_version`,
				args: { quotation: frm.doc.name },
				freeze: true,
			});
			frappe.set_route("Form", "Quotation", name);
		});

		if (frm.doc.docstatus === 1 && !frm.doc.sp_is_approved) {
			frm.add_custom_button(__("Approve Version"), () =>
				frappe.confirm(__("Mark this version as the one the customer accepted?"), async () => {
					await frappe.call({
						method: `${API}.approve_version`,
						args: { quotation: frm.doc.name },
						freeze: true,
					});
					frm.reload_doc();
				})
			);
		}
	},
});
