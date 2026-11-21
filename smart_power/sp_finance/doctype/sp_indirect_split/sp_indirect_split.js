// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A16 Indirect cost split (SP-124): the month's pool beside the stations closed that month and
// the showroom; the admin enters each share (an amount or a %), with no fixed ratio.
frappe.ui.form.on("SP Indirect Split", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.company) frm.set_value("company", frappe.defaults.get_user_default("Company"));
	},
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.company && frm.doc.month) {
			frm.add_custom_button(__("Closed Stations of the Month"), () => sp_split_suggest(frm));
		}
		sp_split_intro(frm);
	},
	month: (frm) => frm.doc.month && frm.doc.company && sp_split_suggest(frm),
	company: (frm) => frm.doc.month && frm.doc.company && sp_split_suggest(frm),
});

async function sp_split_suggest(frm) {
	const s = await frappe.xcall("smart_power.sp_finance.indirect_split.suggest", {
		company: frm.doc.company,
		month: frm.doc.month,
	});
	frm.set_value("pool_amount", s.pool_amount);
	if (!(frm.doc.lines || []).some((r) => flt(r.amount) || flt(r.pct))) {
		frm.clear_table("lines");
		for (const line of s.lines) frm.add_child("lines", line);
		frm.refresh_field("lines");
	}
	sp_split_intro(frm);
}

// the pool and what is left to share, as indicators (Frappe's own intro replaces a saved draft's)
function sp_split_intro(frm) {
	frm.dashboard.clear_headline();
	if (!frm.doc.pool_amount || frm.is_new()) return;
	const left = flt(frm.doc.difference);
	const colour = Math.abs(left) > 1 ? "orange" : "green"; // sp-allow-number: the story's ±1
	frm.dashboard.add_indicator(`${__("Pool")}: ${format_currency(frm.doc.pool_amount)}`, "blue");
	frm.dashboard.add_indicator(`${__("Left to Share")}: ${format_currency(left)}`, colour);
}
