// Shared form components (SP-44). One library so every screen behaves the same way:
//   sp.ui.edit_with_reason(frm, fieldname)   change a saved number with a reason (History + RV2)
//   sp.ui.rule_banner(frm, result)           the business rules a form hits: warn / block
//   sp.ui.confirm_irreversible(title, html, on_yes)   show exactly what will change, then do it
//   sp.ui.center_picker(frm, field) / sp.ui.account_picker(frm, field)   what those fields offer
//   sp.grid.enhance(frm, table)              paste rows from Excel, items matched by code
//   sp.ui.EMPTY_STATES                       an empty list names the next action
// Work date vs entry time is the server's (smart_power.sp_core.dated.SPDatedDocument).
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
			refresh: (frm) => {
				sp.ui.check_rules(frm);
				// a changed value re-checks the rules, once the typing stops
				if (!frm.sp_rule_watch) {
					frm.sp_rule_watch = frappe.utils.debounce(() => sp.ui.check_rules(frm), 400); // sp-allow-number: ms
					frm.$wrapper.on("change", () => frm.sp_rule_watch());
				}
			},
			validate: (frm) => sp.ui.ask_rule_reasons(frm),
		})
	);
});

// --- Pickers (SP-44, components 5 and 6) -------------------------------------------------------
// A center field offers the company's financial centers only; a money account field the official
// accounts and the user's own transit and custody accounts (smart_power.sp_finance.queries).

sp.ui.center_picker = function (frm, fieldname, table) {
	const query = () => ({
		query: "smart_power.sp_finance.queries.center_picker",
		filters: { company: frm.doc.company },
	});
	table ? frm.set_query(fieldname, table, query) : frm.set_query(fieldname, query);
};

sp.ui.account_picker = function (frm, fieldname, table) {
	const query = () => ({
		query: "smart_power.sp_finance.queries.account_picker",
		filters: { company: frm.doc.company },
	});
	table ? frm.set_query(fieldname, table, query) : frm.set_query(fieldname, query);
};

// --- Line-item grid (SP-44, component 7) -------------------------------------------------------
// sp.grid.enhance(frm, "items"): paste rows copied from Excel into the grid: one line per row,
// the item matched by its code (first column), the quantity from the second, the price from the
// price list as for any item (the customer's tier, SP-30). Item search by code or Arabic name is
// the desk's own (SP-29); arrow keys move between rows as in any Frappe grid.
sp.grid = sp.grid || {};

sp.grid.parse_tsv = function (text) {
	return (text || "")
		.split(/\r?\n/)
		.map((line) => line.split("\t").map((c) => c.trim()))
		.filter((cells) => cells.some((c) => c));
};

sp.grid.enhance = function (frm, table) {
	const grid = frm.fields_dict[table] && frm.fields_dict[table].grid;
	if (!grid || grid.sp_enhanced) return;
	grid.sp_enhanced = true;
	grid.wrapper.on("paste", async (e) => {
		const text = (e.originalEvent.clipboardData || window.clipboardData).getData("text");
		const rows = sp.grid.parse_tsv(text);
		// one value is an ordinary paste into a cell; rows of cells are lines to add
		if (rows.length < 2 && (rows[0] || []).length < 2) return; // sp-allow-number: one row of one cell
		e.preventDefault();
		if (frm.doc.docstatus !== 0) return;
		await sp.grid.add_rows(frm, table, rows);
	});
};

sp.grid.add_rows = async function (frm, table, rows) {
	const number = (v) => flt(String(v || "").replace(/,/g, ""));
	// a header row (no number in the quantity column) is skipped
	const lines = rows.filter((cells, i) => !(i === 0 && cells.length > 1 && !number(cells[1])));
	const { found, missing } = await frappe.xcall("smart_power.sp_stock.paste.match_items", {
		codes: lines.map((cells) => cells[0]),
	});
	let added = 0;
	for (const cells of lines) {
		const item_code = found[cells[0]];
		if (!item_code) continue;
		const row = frm.add_child(table);
		await frappe.model.set_value(row.doctype, row.name, "item_code", item_code);
		await frappe.model.set_value(row.doctype, row.name, "qty", number(cells[1]) || 1);
		added += 1;
	}
	frm.refresh_field(table);
	frappe.show_alert({ message: __("{0} lines added", [added]), indicator: "green" });
	if (missing.length) {
		frappe.msgprint({
			title: __("Not found"),
			indicator: "orange",
			message: __("These codes match no item: {0}", [missing.map(frappe.utils.escape_html).join(", ")]),
		});
	}
	return { added, missing };
};

// --- Empty states (SP-44, component 8) ---------------------------------------------------------
// An empty list names the next action ("لا توجد مدفوعات — سجّل أول دفعة"), with its button.
sp.ui.EMPTY_STATES = {
	"SP Customer Payment": {
		title: __("No payments yet"),
		description: __("Record the first payment."),
		label: __("Record a payment"),
		action: () => smart_power.shell && smart_power.shell.start({ kind: "dialog", target: "payment" }),
	},
	"SP Case": {
		title: __("No requests yet"),
		description: __("Take the first quote request."),
		label: __("New quote request"),
		action: () => frappe.set_route("sp-quote-request"),
	},
	"SP Simple Record": {
		title: __("No simple records yet"),
		description: __("Record a storage fee, a small income or a one-off expense."),
		label: __("New simple record"),
		action: () => frappe.new_doc("SP Simple Record"),
	},
};

$(document).on("app_ready", () => {
	const ListView = frappe.views && frappe.views.ListView;
	if (!ListView || ListView.prototype.sp_empty_states) return;
	const original = ListView.prototype.get_no_result_message;
	ListView.prototype.get_no_result_message = function () {
		const state = sp.ui.EMPTY_STATES[this.doctype];
		const filters = this.filter_area && this.filter_area.get();
		if (!state || (filters && filters.length)) return original.call(this);
		const esc = frappe.utils.escape_html;
		setTimeout(() => this.$no_result && this.$no_result.find(".sp-empty-action").off("click").on("click", state.action));
		return `<div class="no-result text-muted flex justify-center align-center">
			<div class="text-center">
				<div class="h6 mb-2">${esc(state.title)} — ${esc(state.description)}</div>
				<button class="btn btn-primary btn-sm sp-empty-action">${esc(state.label)}</button>
			</div></div>`;
	};
	ListView.prototype.sp_empty_states = true;
});

// The line grids that take a paste from Excel.
["Quotation", "Purchase Order"].forEach((doctype) =>
	frappe.ui.form.on(doctype, { refresh: (frm) => sp.grid.enhance(frm, "items") })
);
