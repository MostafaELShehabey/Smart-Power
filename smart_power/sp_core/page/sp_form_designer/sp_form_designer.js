// X3 Fields and forms (SP-132): add, hide, reorder and require fields on the SP forms, and the
// quote request's questions per system type. The server is smart_power.sp_core.form_designer;
// every change is applied at once and recorded in the audit log.
const SP_FD = "smart_power.sp_core.form_designer";
const SP_FD_KINDS = [
	["text", "Text"],
	["long_text", "Long Text"],
	["number", "Number"],
	["money", "Money"],
	["date", "Date"],
	["list", "List"],
	["file", "File"],
	["link", "Link"],
	["check", "Yes or No"],
];
const SP_FD_REQUEST_KINDS = ["text", "long_text", "number", "list", "check"];
const SP_FD_REQUEST = "request:";

frappe.pages["sp-form-designer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Fields and Forms"), single_column: true });
	wrapper.sp_designer = new SPFormDesigner(page);
};

frappe.pages["sp-form-designer"].on_page_show = function (wrapper) {
	wrapper.sp_designer.refresh_forms();
};

class SPFormDesigner {
	constructor(page) {
		this.page = page;
		this.form_field = page.add_field({
			fieldtype: "Select",
			fieldname: "form",
			label: __("Form"),
			change: () => this.open(this.form_field.get_value()),
		});
		page.set_primary_action(__("Add Field"), () => this.add(), "add");
		page.add_inner_button(__("New List"), () => this.new_list());
		this.$body = $('<div class="sp-fd"></div>').appendTo(page.main);
		this.$body.on("click", "[data-act]", (e) => this.act(e.currentTarget));
	}

	async refresh_forms() {
		const { message } = await frappe.call(`${SP_FD}.forms`);
		this.meta = message;
		const options = [""];
		for (const t of message.request_types) options.push({ value: SP_FD_REQUEST + t.name, label: __("Quote request: {0}", [t.label]) });
		for (const f of message.forms) options.push({ value: f.doctype, label: `${f.module} · ${f.label}` });
		this.form_field.df.options = options;
		this.form_field.refresh();
		if (this.current) this.form_field.set_value(this.current);
	}

	is_request() {
		return (this.current || "").startsWith(SP_FD_REQUEST);
	}

	async open(value) {
		this.current = value;
		this.$body.empty();
		if (!value) return;
		const { message } = this.is_request()
			? await frappe.call(`${SP_FD}.request_load`, { system_type: value.slice(SP_FD_REQUEST.length) })
			: await frappe.call(`${SP_FD}.load`, { doctype: value });
		this.show(message);
	}

	show(data) {
		this.data = data;
		const request = this.is_request();
		const rows = data.fields
			.map((f) => {
				if (f.section) return `<tr class="sp-fd-section"><td colspan="6">${frappe.utils.escape_html(f.label || "")}</td></tr>`;
				const when = f.when ? frappe.utils.escape_html(f.when.text) : "";
				const name = frappe.utils.escape_html(f.fieldname);
				return `<tr class="${f.hidden ? "sp-fd-hidden" : ""}">
					<td>${frappe.utils.escape_html(f.label)}${f.custom ? ` <span class="sp-fd-tag">${__("Added")}</span>` : ""}</td>
					<td>${__(f.fieldtype)}</td>
					<td><input type="checkbox" data-act="reqd" data-field="${name}" ${f.reqd ? "checked" : ""}></td>
					<td>${request ? "" : `<input type="checkbox" data-act="hidden" data-field="${name}" ${f.hidden ? "checked" : ""}>`}</td>
					<td>${request ? "" : `${when} <button class="btn btn-xs btn-default" data-act="when" data-field="${name}">${__("Show Only When")}</button>`}</td>
					<td class="sp-fd-move">
						<button class="btn btn-xs btn-default" data-act="up" data-field="${name}">▲</button>
						<button class="btn btn-xs btn-default" data-act="down" data-field="${name}">▼</button>
						${request ? `<button class="btn btn-xs btn-default" data-act="remove" data-field="${name}">${__("Remove")}</button>` : ""}
					</td></tr>`;
			})
			.join("");
		this.$body.html(`<h4>${frappe.utils.escape_html(data.label)}</h4>
			<p class="text-muted">${request ? __("The questions this system type's quote request asks.") : __("Hiding a field keeps the records' values; show it again at any time.")}</p>
			<div class="sp-fd-table"><table class="table table-bordered table-sm"><thead><tr>
			<th>${__("Field")}</th><th>${__("Type")}</th><th>${__("Required")}</th><th>${request ? "" : __("Hidden")}</th><th>${request ? "" : __("Shown")}</th><th></th>
			</tr></thead><tbody>${rows}</tbody></table></div>`);
	}

	async change(fieldname, spec) {
		const args = this.is_request()
			? { method: `${SP_FD}.request_change`, args: { system_type: this.current.slice(SP_FD_REQUEST.length), fieldname, spec } }
			: { method: `${SP_FD}.change_field`, args: { doctype: this.current, fieldname, spec } };
		const { message } = await frappe.call({ ...args, freeze: true });
		this.show(message);
		frappe.show_alert({ message: __("Saved: forms already open show it after a reload."), indicator: "green" });
	}

	act(el) {
		const fieldname = el.dataset.field;
		const act = el.dataset.act;
		if (act === "reqd" || act === "hidden") return this.change(fieldname, { [act]: el.checked ? 1 : 0 });
		if (act === "up" || act === "down") return this.change(fieldname, { move: act });
		if (act === "remove") return frappe.confirm(__("Remove this question? Old requests keep their answers."), () => this.change(fieldname, { remove: 1 }));
		if (act === "when") return this.when(fieldname);
	}

	choices(dialog, field_key, value_key) {
		// the value picker offers the chosen field's own values
		const c = (this.data.conditions || []).find((x) => x.fieldname === dialog.get_value(field_key));
		dialog.set_df_property(value_key, "options", c ? c.options : []);
	}

	when(fieldname) {
		const conditions = this.data.conditions || [];
		const d = new frappe.ui.Dialog({
			title: __("Show Only When"),
			fields: [
				{ fieldname: "field", fieldtype: "Select", label: __("Field"), options: [""].concat(conditions.map((c) => ({ value: c.fieldname, label: c.label }))), onchange: () => this.choices(d, "field", "value") },
				{ fieldname: "value", fieldtype: "Autocomplete", label: __("Has the Value"), options: [], description: __("Empty the field to always show it.") },
			],
			primary_action_label: __("Save"),
			primary_action: (v) => {
				d.hide();
				this.change(fieldname, { when: v.field ? { field: v.field, value: v.value || "" } : {} });
			},
		});
		d.show();
	}

	add() {
		if (!this.current) return frappe.msgprint(__("Pick a form first."));
		const request = this.is_request();
		const kinds = SP_FD_KINDS.filter(([k]) => !request || SP_FD_REQUEST_KINDS.includes(k));
		const fields = [
			{ fieldname: "label", fieldtype: "Data", label: __("Label"), reqd: 1 },
			{ fieldname: "label_en", fieldtype: "Data", label: __("English Label"), description: __("Optional: it also names the field.") },
			{ fieldname: "kind", fieldtype: "Select", label: __("Type"), reqd: 1, options: kinds.map(([value, label]) => ({ value, label: __(label) })) },
			{ fieldname: "list", fieldtype: "Select", label: __("List"), depends_on: "eval:doc.kind=='list'", options: [""].concat(this.meta.lists.map((l) => ({ value: l.name, label: l.label }))) },
			{ fieldname: "after", fieldtype: "Select", label: __("After"), options: [""].concat(this.data.fields.map((f) => ({ value: f.fieldname, label: f.label }))) },
			{ fieldname: "reqd", fieldtype: "Check", label: __("Required") },
		];
		if (!request) {
			fields.splice(fields.findIndex((f) => f.fieldname === "after"), 0, { fieldname: "link", fieldtype: "Link", label: __("Links To"), options: "DocType", depends_on: "eval:doc.kind=='link'" });
			fields.push(
				{ fieldname: "when_field", fieldtype: "Select", label: __("Show Only When"), options: [""].concat((this.data.conditions || []).map((c) => ({ value: c.fieldname, label: c.label }))), onchange: () => this.choices(d, "when_field", "when_value") },
				{ fieldname: "when_value", fieldtype: "Autocomplete", label: __("Has the Value"), options: [], depends_on: "eval:doc.when_field" }
			);
		}
		const d = new frappe.ui.Dialog({
			title: __("Add Field"),
			fields,
			primary_action_label: __("Add"),
			primary_action: async (v) => {
				const spec = { ...v };
				if (v.when_field) spec.when = { field: v.when_field, value: v.when_value || "" };
				const call = request
					? { method: `${SP_FD}.request_add`, args: { system_type: this.current.slice(SP_FD_REQUEST.length), spec } }
					: { method: `${SP_FD}.add_field`, args: { doctype: this.current, spec } };
				const { message } = await frappe.call({ ...call, freeze: true });
				d.hide();
				this.show(message);
				frappe.show_alert({ message: __("Field added"), indicator: "green" });
			},
		});
		d.show();
	}

	new_list() {
		const fields = [
			{ fieldname: "list_title", fieldtype: "Data", label: __("List Name (English)"), reqd: 1, description: __("Its key, for example Soil Type.") },
			{ fieldname: "list_title_ar", fieldtype: "Data", label: __("List Name (Arabic)"), reqd: 1 },
		];
		frappe.prompt(fields, async ({ list_title, list_title_ar }) => {
			const { message } = await frappe.call({ method: `${SP_FD}.new_list`, args: { name: list_title, label_ar: list_title_ar }, freeze: true });
			this.meta.lists = message;
			frappe.show_alert({ message: __("List {0} made: add its values in Lists.", [list_title_ar]), indicator: "green" });
		}, __("New List"));
	}
}

frappe.dom.set_style(`
.sp-fd-table { overflow-x: auto; }
.sp-fd-table td { vertical-align: middle; }
.sp-fd-section td { background: var(--subtle-fg); font-weight: bold; }
.sp-fd-hidden td:first-child { color: var(--text-muted); text-decoration: line-through; }
.sp-fd-tag { font-size: 11px; padding: 0 6px; border-radius: 8px; background: var(--bg-blue); }
.sp-fd-move { white-space: nowrap; }
`);
