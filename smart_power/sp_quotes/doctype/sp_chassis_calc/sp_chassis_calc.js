// The chassis calc (SP-166): the review on top; everything is recalculated on save.
frappe.ui.form.on("SP Chassis Calc", {
	refresh(frm) {
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
