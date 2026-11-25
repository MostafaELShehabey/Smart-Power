// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// SH2 Showroom cash box (SP-104): the day's movements, the expected closing, the day close, and a
// red banner when the box holds cash too long or over its limit. SH3 (SP-105): the deposit
// dialog from the box, and the deposits waiting for the admin on their own line.
const SP_CB_API = "smart_power.sp_finance.cash_box";

frappe.ui.form.on("SP Cash Box Day", {
	refresh(frm) {
		const s = frm.doc.__onload?.sp_cash_box || {};
		sp_cb_banner(frm, s.held || {});
		sp_cb_lines(frm, s.moves || {}, s.pending_deposits || []);
		if (frm.is_new()) return;
		if (frm.doc.status === "Open") {
			frm.add_custom_button(__("Record Expense"), () =>
				frappe.new_doc("SP Expense", {
					company: frm.doc.company,
					work_date: frm.doc.day,
					center_type: "Showroom",
					paid_from_kind: "Shop cash",
				})
			);
			frm.add_custom_button(__("Record Bank Deposit"), () =>
				smart_power.transfer_dialog({ company: frm.doc.company, from_account: frm.doc.cash_account }, () =>
					frm.reload_doc()
				)
			);
			frm.add_custom_button(__("Close the Day"), () => sp_cb_close(frm)).addClass("btn-primary");
		}
		if (frm.doc.reject_reason && frm.doc.status === "Open") {
			frm.dashboard.set_headline(`${__("Sent back")}: ${frappe.utils.escape_html(frm.doc.reject_reason)}`, "orange");
		}
	},
});

function sp_cb_banner(frm, h) {
	if (!h.over_days && !h.over_cash) return;
	const parts = [];
	if (h.over_days) parts.push(__("cash held {0} days (limit {1})", [h.days, h.day_limit]));
	if (h.over_cash) parts.push(__("{0} in the box (limit {1})", [format_currency(h.balance), format_currency(h.cash_limit)]));
	frm.set_intro(`${__("Deposit the cash")}: ${parts.join(" · ")}`, "red");
}

function sp_cb_lines(frm, m, pending) {
	const field = frm.fields_dict.lines_html;
	if (!field) return;
	const esc = frappe.utils.escape_html;
	const rows = [];
	for (const r of m.payments || []) rows.push([__("Station payment"), `${esc(r.customer_name || "")} · ${esc(r.station || "")}`, r.amount, r.name, "SP Customer Payment"]);
	for (const r of m.expenses || []) rows.push([__("Expense"), esc(r.expense_type_name || r.expense_type || "") + (r.note ? ` · ${esc(r.note)}` : ""), -r.amount, r.name, "SP Expense"]);
	const waiting = (r) => (r.status === "Pending" ? ` <span class="indicator-pill orange">${__("Waiting for the admin")}</span>` : "");
	for (const r of m.deposits || [])
		rows.push([__("Bank deposit"), esc(r.to_account || "") + waiting(r), -r.amount, r.name, "SP Transfer"]);
	const body = rows.length
		? rows
				.map(
					([kind, what, amount, name, doctype]) =>
						`<tr><td>${kind}</td><td>${what}</td><td class="text-right">${format_currency(amount)}</td>` +
						`<td><a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${esc(name)}</a></td></tr>`
				)
				.join("")
		: `<tr><td colspan="4" class="text-muted">${__("No movements yet today.")}</td></tr>`;
	// deposits in transit: out of the box, not yet in the bank, whatever day they were recorded
	const total = pending.reduce((sum, r) => sum + r.amount, 0);
	const foot = pending.length
		? `<tfoot><tr class="text-warning"><td>${__("Deposits pending")}</td>` +
			`<td>${pending.map((r) => esc(r.name)).join("، ")}</td>` +
			`<td class="text-right">${format_currency(total)}</td><td>${__("Waiting for the admin")}</td></tr></tfoot>`
		: "";
	field.$wrapper.html(`<table class="table table-sm"><tbody>${body}</tbody>${foot}</table>`);
}

async function sp_cb_close(frm) {
	await frm.reload_doc(); // an expense or deposit recorded since the form opened (BUG-15)
	const dialog = new frappe.ui.Dialog({
		title: __("Close the Day"),
		fields: [
			{ fieldtype: "HTML", options: `<p>${__("Expected Closing")}: <b>${format_currency(frm.doc.expected_closing)}</b></p>` },
			{ fieldname: "counted", fieldtype: "Currency", label: __("Counted"), reqd: 1 },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), description: __("Needed when the count differs.") },
		],
		primary_action_label: __("Close the Day"),
		primary_action: async (values) => {
			await frappe.xcall(`${SP_CB_API}.close_day`, { name: frm.doc.name, ...values });
			dialog.hide();
			frappe.show_alert({ message: __("Sent to the admin to confirm."), indicator: "green" });
			frm.reload_doc();
		},
	});
	dialog.show();
}
