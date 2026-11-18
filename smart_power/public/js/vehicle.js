// A vehicle's oil change at a glance (SP-106).
frappe.ui.form.on("Vehicle", {
	refresh(frm) {
		if (frm.is_new()) return;
		const left = (frm.doc.sp_next_oil_km || 0) - (frm.doc.sp_odometer_km || 0);
		const late = left < 0;
		frm.set_intro(late ? __("Oil change is {0} km late", [-left]) : __("{0} km to oil", [left]), late ? "red" : "blue");
	},
});
