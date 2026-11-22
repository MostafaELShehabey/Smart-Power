// The chassis calc (SP-166): the review on top; everything is recalculated on save.
frappe.ui.form.on("SP Chassis Calc", {
	async quotation(frm) {
		// the customer, the panel and its count from the quote (SP-167)
		if (!frm.doc.quotation) return;
		const { message: info } = await frappe.call({
			method: "smart_power.sp_quotes.chassis_quote.from_quote",
			args: { quotation: frm.doc.quotation },
		});
		frm.set_value("customer_name", info.customer_name);
		if (info.panel_item && !frm.doc.panel_item) frm.set_value("panel_item", info.panel_item);
		if (info.panels && !(frm.doc.arrays || []).length) {
			frm.add_child("arrays", { panels: info.panels });
			frm.refresh_field("arrays");
		}
	},
	onload(frm) {
		if (frm.is_new() && frm.doc.quotation) frm.trigger("quotation");
	},
	refresh(frm) {
		if (!frm.is_new() && frm.doc.quotation) {
			frm.add_custom_button(__("Open Quotation"), () => frappe.set_route("Form", "Quotation", frm.doc.quotation));
		}
		const review = (frm.doc.review || "").trim();
		if (!frm.is_new() && review) {
			const ok = review === "✓";
			frm.set_intro(ok ? __("All arrays pass the check.") : review, ok ? "green" : "red");
		}
		if (!frm.is_new() && frm.doc.factory) {
			frm.add_custom_button(__("Price List"), () =>
				frappe.set_route("query-report", "SP Chassis Price List", { factory: frm.doc.factory })
			);
		}
	},
});
