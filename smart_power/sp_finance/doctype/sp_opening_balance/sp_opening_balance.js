// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// A15 Opening balances (SP-160): download the template, attach it filled, check it, then the
// admin posts it once; Reconcile compares the opening trial balance with the template's.
// The rules are on the server (smart_power.sp_finance.opening).
const SP_OB_API = "smart_power.sp_finance.opening";

frappe.ui.form.on("SP Opening Balance", {
	refresh(frm) {
		frm.add_custom_button(__("Download Template"), () => {
			window.open(`/api/method/${SP_OB_API}.template`);
		});
		if (frm.is_new()) return;
		if (frm.doc.status !== "Posted") {
			frm.add_custom_button(__("Check"), () => sp_ob_check(frm));
		}
		const admin = frappe.user.has_role("SP Admin") || frappe.user.has_role("System Manager");
		if (frm.doc.status === "Checked" && admin) {
			frm.add_custom_button(__("Post Opening"), () => sp_ob_post(frm)).addClass("btn-primary");
		}
		if (frm.doc.status === "Posted") {
			frm.add_custom_button(__("Reconcile"), () => sp_ob_reconcile(frm));
		}
		sp_ob_render(frm);
	},
});

async function sp_ob_check(frm) {
	if (frm.is_dirty()) await frm.save();
	await frappe.call({ method: `${SP_OB_API}.run_check`, args: { name: frm.doc.name }, freeze: true });
	frm.reload_doc();
}

function sp_ob_post(frm) {
	frappe.confirm(__("Post the opening on {0}? It is posted once and cannot be undone here.", [frappe.datetime.str_to_user(frm.doc.opening_date)]), async () => {
		const { message } = await frappe.call({ method: `${SP_OB_API}.post`, args: { name: frm.doc.name }, freeze: true });
		frappe.show_alert({ message, indicator: "blue" });
		setTimeout(() => frm.reload_doc(), 3000); // sp-allow-number: give the job a moment
	});
}

async function sp_ob_reconcile(frm) {
	await frappe.call({ method: `${SP_OB_API}.reconcile`, args: { name: frm.doc.name }, freeze: true });
	frm.reload_doc();
}

function sp_ob_render(frm) {
	const esc = frappe.utils.escape_html;
	const money = (v) => esc(format_currency(v));
	const parts = [];
	const check = frm.doc.check_json ? JSON.parse(frm.doc.check_json) : null;
	if (check) {
		parts.push(`<table class="table table-sm"><thead><tr><th>${esc(__("Sheet"))}</th><th class="text-right">${esc(__("Rows"))}</th><th class="text-right">${esc(__("Amount"))}</th></tr></thead><tbody>${check.sections
			.map((s) => `<tr><td>${esc(s.sheet)}</td><td class="text-right">${s.rows}</td><td class="text-right">${money(s.amount)}</td></tr>`)
			.join("")}</tbody></table>`);
		parts.push(`<p><b>${esc(__("Owner's equity (the balancing figure)"))}:</b> ${money(check.equity)} ${esc(check.equity < 0 ? __("debit") : __("credit"))}</p>`);
		if (check.errors.length) {
			parts.push(`<div class="text-danger mb-2"><b>${esc(__("{0} problems to fix", [check.errors.length]))}</b></div><table class="table table-sm"><tbody>${check.errors
				.map((e) => `<tr><td>${esc(e.sheet)}</td><td>${e.row ? esc(__("Row {0}", [e.row])) : ""}</td><td>${esc(e.message)}</td></tr>`)
				.join("")}</tbody></table>`);
		} else {
			parts.push(`<div class="text-success">${esc(__("No problems found."))}</div>`);
		}
	}
	const rec = frm.doc.reconcile_json ? JSON.parse(frm.doc.reconcile_json) : null;
	if (rec) {
		parts.push(`<h5 class="mt-4">${esc(rec.matches ? __("The trial balance matches the template.") : __("The trial balance does not match the template."))}</h5>`);
		parts.push(`<table class="table table-sm"><thead><tr><th>${esc(__("Account"))}</th><th class="text-right">${esc(__("Template"))}</th><th class="text-right">${esc(__("Posted"))}</th><th class="text-right">${esc(__("Difference"))}</th></tr></thead><tbody>${rec.rows
			.map((r) => `<tr class="${r.matches ? "" : "text-danger"}"><td>${esc(r.account)}${r.in_template ? "" : ` <span class="indicator-pill orange">${esc(__("Not in the template"))}</span>`}</td><td class="text-right">${money(r.expected)}</td><td class="text-right">${money(r.actual)}</td><td class="text-right">${money(r.difference)}</td></tr>`)
			.join("")}</tbody></table>`);
	}
	frm.get_field("check_result").$wrapper.html(parts.join(""));
}
