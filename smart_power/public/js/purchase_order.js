// A shared order (SP-83): the stations' amounts against the order's total, as they are typed.
frappe.ui.form.on("Purchase Order", {
	refresh: (frm) => show_split(frm),
	base_net_total: (frm) => show_split(frm),
});

frappe.ui.form.on("SP PO Station Split", {
	amount: (frm) => show_split(frm),
	sp_station_splits_remove: (frm) => show_split(frm),
});

function show_split(frm) {
	const field = frm.get_field("sp_station_splits");
	if (!field || !field.$wrapper) return;
	field.$wrapper.find(".sp-split-total").remove();
	const rows = frm.doc.sp_station_splits || [];
	if (!rows.length) return;
	const split = rows.reduce((sum, r) => sum + flt(r.amount), 0);
	const total = flt(frm.doc.base_net_total);
	const left = total - split;
	const fmt = (v) => format_currency(v, frm.doc.company_currency || frm.doc.currency);
	const ok = Math.abs(left) <= 1;
	const text = ok
		? __("The stations' amounts add up to the order's total of {0}.", [fmt(total)])
		: __("The stations' amounts add up to {0} of {1}: {2} left.", [fmt(split), fmt(total), fmt(left)]); // sp-allow-number: placeholders
	$(`<div class="sp-split-total small ${ok ? "text-success" : "text-danger"}" style="margin-top:6px"></div>`)
		.text(text)
		.appendTo(field.$wrapper);
}
