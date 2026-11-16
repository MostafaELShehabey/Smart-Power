// G7 Simple record (SP-43): the type proposes the direction; a station brings its center.
frappe.ui.form.on("SP Simple Record", {
	setup(frm) {
		// Cancel reverses the record's entry with a new entry; it never cancels the entry itself
		frm.ignore_doctypes_on_cancel_all = ["Journal Entry"];
		frm.set_query("account", () => ({
			filters: { company: frm.doc.company, is_group: 0, root_type: ["in", ["Asset", "Liability"]] },
		}));
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		// Submit posts money: show exactly the entry first (SP-44)
		frm.savesubmit = async function () {
			const lines = await frappe.xcall("smart_power.sp_finance.simple_record.preview", { doc: frm.doc });
			sp.ui.confirm_irreversible(__("Submit and post"), sp.ui.entry_preview_html(lines), () => frm.save("Submit"));
		};
	},
	async record_type(frm) {
		if (!frm.doc.record_type) return;
		const direction = await frappe.xcall("smart_power.sp_finance.simple_record.type_direction", {
			record_type: frm.doc.record_type,
		});
		if (direction) frm.set_value("direction", direction);
	},
});
