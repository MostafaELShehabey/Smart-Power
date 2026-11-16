// Shared form components (SP-44). One library so every screen behaves the same way:
//   sp.ui.edit_with_reason(frm, fieldname)   change a saved number with a reason (History + RV2)
//   sp.ui.rule_banner(frm, result)           the business rules a form hits: warn / block
//   sp.ui.confirm_irreversible(title, html, on_yes)   show exactly what will change, then do it
// The server side is smart_power.audit (the fields registered there get the button by themselves).
window.sp = window.sp || {};
sp.ui = sp.ui || {};

sp.ui.edit_with_reason = function (frm, fieldname) {
	const df = frappe.meta.get_docfield(frm.doctype, fieldname, frm.doc.name);
	const label = __(df.label);
	const d = new frappe.ui.Dialog({
		title: __("Change {0}", [label]),
		fields: [
			{ fieldname: "old", fieldtype: df.fieldtype, label: __("Now"), options: df.options, read_only: 1, default: frm.doc[fieldname] },
			{ fieldname: "value", fieldtype: df.fieldtype, label: __("New value"), options: df.options, reqd: 1 },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1,
				description: __("It goes to the document's history and to the admin's review.") },
		],
		primary_action_label: __("Change"),
		primary_action: async (v) => {
			await frappe.xcall("smart_power.audit.edit_field", {
				doctype: frm.doctype, name: frm.doc.name, fieldname, value: v.value, reason: v.reason,
			});
			d.hide();
			frappe.show_alert({ message: __("{0} changed", [label]), indicator: "green" });
			frm.reload_doc();
		},
	});
	d.show();
};

// Every form whose doctype registers fields in smart_power.audit.EDITABLE gets a
// "Change … (with reason)" button for each field this user may change.
$(document).on("form-refresh", async (e, frm) => {
	if (!frm || frm.is_new() || !(frappe.boot.sp_editable || []).includes(frm.doctype)) return;
	const fields = await frappe.xcall("smart_power.audit.editable_fields", { doctype: frm.doctype, name: frm.doc.name });
	fields.forEach((f) =>
		frm.add_custom_button(
			__("Change {0} (with reason)", [__(frappe.meta.get_label(frm.doctype, f, frm.doc.name))]),
			() => sp.ui.edit_with_reason(frm, f)
		)
	);
});

// --- Rule banner (SP-44, component 2) ---------------------------------------------------------
// Yellow for a warning (continuing asks for a reason), red for a block (the primary button is
// off, unless the admin overrides with a reason). Fed by smart_power.rules.check.

sp.ui.rule_banner = function (frm, result) {
	const esc = frappe.utils.escape_html;
	frm.$wrapper.find(".sp-rule-banner").remove();
	const hits = (result && result.hits) || [];
	frm.sp_rule_hits = hits;
	const blocked = hits.filter((h) => h.level === "Block");
	if (frm.page.btn_primary) frm.page.btn_primary.prop("disabled", blocked.length && !result.can_override);
	if (!hits.length) return;
	const red = blocked.length > 0;
	const $banner = $(`<div class="sp-rule-banner alert ${red ? "alert-danger" : "alert-warning"} mb-3" role="alert">
		<div class="font-weight-bold mb-1">${esc(red ? __("Blocked by a business rule") : __("Check before you continue"))}</div>
		<ul class="mb-0">${hits
			.map(
				(h) => `<li><b>${esc(h.title)}</b>: ${esc(h.message)}${h.suggestion ? " — " + esc(h.suggestion) : ""}</li>`
			)
			.join("")}</ul></div>`);
	$banner.prependTo(frm.layout.wrapper);
};

sp.ui.check_rules = async function (frm) {
	if (frm.doc.docstatus > 0) return sp.ui.rule_banner(frm, null);
	const result = await frappe.xcall("smart_power.rules.check", { doc: frm.doc });
	sp.ui.rule_banner(frm, result);
	return result;
};

// On save: a warning that needs a reason (or a block the admin overrides) asks for it first.
sp.ui.ask_rule_reasons = async function (frm) {
	const result = await sp.ui.check_rules(frm);
	const needed = ((result && result.hits) || []).filter((h) => h.needs_reason);
	if (!needed.length) return;
	if (needed.some((h) => h.level === "Block") && !result.can_override) {
		frappe.validated = false;
		return;
	}
	const values = await new Promise((resolve) => {
		const d = new frappe.ui.Dialog({
			title: __("A reason is needed"),
			fields: needed.map((h) => ({
				fieldname: h.rule, fieldtype: "Small Text", label: h.title, reqd: 1, description: h.message,
			})),
			primary_action_label: __("Continue"),
			primary_action: (v) => { d.hide(); resolve(v); },
			on_hide: () => resolve(null),
		});
		d.show();
	});
	if (!values) {
		frappe.validated = false;
		return;
	}
	frm.doc.__sp_rule_reasons = JSON.stringify(values);
};

// --- Confirmation for irreversible actions (SP-44, component 3) ---------------------------------
// Shows exactly what will change (e.g. the entry's lines) before confirm, post, close, write-off.

sp.ui.confirm_irreversible = function (title, html_preview, on_yes) {
	const d = new frappe.ui.Dialog({
		title,
		fields: [{ fieldname: "preview", fieldtype: "HTML", options: html_preview }],
		primary_action_label: __("Yes, go ahead"),
		primary_action: () => { d.hide(); on_yes(); },
		secondary_action_label: __("Go Back"),
	});
	d.show();
	return d;
};

// The lines of an entry, as the confirmation shows them.
sp.ui.entry_preview_html = function (lines) {
	const esc = frappe.utils.escape_html;
	if (!lines || !lines.length) return `<div class="text-muted">${esc(__("Nothing posts."))}</div>`;
	const row = (l) => `<tr><td>${esc(l.account)}</td><td>${esc(l.cost_center || "")}</td>
		<td class="text-right">${l.debit ? esc(format_currency(l.debit)) : ""}</td>
		<td class="text-right">${l.credit ? esc(format_currency(l.credit)) : ""}</td></tr>`;
	return `<table class="table table-sm table-bordered"><thead><tr><th>${esc(__("Account"))}</th>
		<th>${esc(__("Center"))}</th><th>${esc(__("Debit"))}</th><th>${esc(__("Credit"))}</th></tr></thead>
		<tbody>${lines.map(row).join("")}</tbody></table>`;
};

// The forms with rules show the banner and ask for reasons on save.
$(document).on("app_ready", () => {
	(frappe.boot.sp_rule_doctypes || []).forEach((doctype) =>
		frappe.ui.form.on(doctype, {
			refresh: (frm) => sp.ui.check_rules(frm),
			validate: (frm) => sp.ui.ask_rule_reasons(frm),
		})
	);
});
