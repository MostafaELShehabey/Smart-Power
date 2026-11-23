// X2 Permissions matrix (SP-131): the admin ticks what a role sees and does, per menu group and
// document type, with the field and row rules; clone a role; preview its menu. The server is
// smart_power.sp_core.permissions_matrix; a save lists every change before it is made.
const SP_PM = "smart_power.sp_core.permissions_matrix";
const SP_PM_COLS = [
	["view", "View"],
	["create", "Create"],
	["edit", "Edit"],
	["delete", "Delete"],
	["confirm", "Confirm"],
	["export", "Export"],
	["own", "Own Records Only"],
	["assigned", "Assigned to Me Only"],
];

frappe.pages["sp-permissions-matrix"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Permissions Matrix"), single_column: true });
	wrapper.sp_matrix = new SPPermissionsMatrix(page);
};

frappe.pages["sp-permissions-matrix"].on_page_show = function (wrapper) {
	wrapper.sp_matrix.refresh_roles();
};

class SPPermissionsMatrix {
	constructor(page) {
		this.page = page;
		this.role = null;
		this.data = null;
		this.role_field = page.add_field({
			fieldtype: "Select",
			fieldname: "role",
			label: __("Role"),
			change: () => this.load(this.role_field.get_value()),
		});
		page.set_primary_action(__("Save"), () => this.save(), "check");
		page.add_inner_button(__("New Role"), () => this.new_role());
		page.add_inner_button(__("Clone Role"), () => this.clone());
		page.add_inner_button(__("Preview Menu"), () => this.preview());
		this.$body = $('<div class="sp-pm"></div>').appendTo(page.main);
		this.$body.on("change", "input[data-dt]", (e) => this.tick(e.currentTarget));
		this.$body.on("change", "input[data-module]", (e) => this.tick_module(e.currentTarget));
		this.$body.on("change", "input[data-field]", (e) => (this.fields[e.currentTarget.dataset.field] = e.currentTarget.checked));
	}

	async refresh_roles(select) {
		const { message } = await frappe.call(`${SP_PM}.roles`);
		this.roles = message;
		this.role_field.df.options = [""].concat(message.map((r) => ({ value: r.role, label: r.label })));
		this.role_field.refresh();
		if (select || this.role) this.role_field.set_value(select || this.role);
	}

	async load(role) {
		this.role = role;
		this.$body.empty();
		if (!role) return;
		const { message } = await frappe.call(`${SP_PM}.load`, { role });
		this.data = message;
		this.want = {};
		this.fields = {};
		this.render();
	}

	state(dt) {
		return Object.assign({}, dt, this.want[dt.doctype] || {});
	}

	render() {
		const d = this.data;
		const locked = d.locked;
		let html = "";
		if (locked) html += `<p class="sp-pm-locked">${__("{0} always keeps its access; the matrix does not change it.", [__(d.role)])}</p>`;
		html += `<div class="sp-pm-fields"><b>${__("Field Rules")}</b>`;
		for (const f of d.fields) {
			const checked = (this.fields[f.key] ?? f.state === "all") ? "checked" : "";
			html += `<label><input type="checkbox" data-field="${f.key}" ${checked} ${locked ? "disabled" : ""}> ${frappe.utils.escape_html(f.label)}${f.state === "some" ? ` <small>(${__("partly")})</small>` : ""}</label>`;
		}
		html += `</div><div class="sp-pm-table"><table class="table table-bordered table-sm"><thead><tr><th>${__("Document Type")}</th>`;
		html += SP_PM_COLS.map(([, label]) => `<th>${__(label)}</th>`).join("") + "</tr></thead><tbody>";
		for (const m of d.modules) {
			html += `<tr class="sp-pm-module"><td><b>${frappe.utils.escape_html(m.label)}</b></td>`;
			for (const [key] of SP_PM_COLS) {
				const values = m.doctypes.map((dt) => this.state(dt)[key]).filter((v) => v !== null && v !== undefined);
				const on = values.filter((v) => v === true || v === "all").length;
				html += values.length
					? `<td><input type="checkbox" data-module="${frappe.utils.escape_html(m.module)}" data-key="${key}" ${on === values.length ? "checked" : ""} data-some="${on && on < values.length ? 1 : 0}" ${locked ? "disabled" : ""}></td>`
					: "<td></td>";
			}
			html += "</tr>";
			for (const dt of m.doctypes) {
				const s = this.state(dt);
				html += `<tr><td class="sp-pm-dt">${frappe.utils.escape_html(dt.label)}</td>`;
				for (const [key] of SP_PM_COLS) {
					const v = s[key];
					if (v === null || v === undefined) {
						html += "<td></td>";
						continue;
					}
					const on = v === true || v === "all";
					html += `<td><input type="checkbox" data-dt="${frappe.utils.escape_html(dt.doctype)}" data-key="${key}" ${on ? "checked" : ""} data-some="${v === "some" ? 1 : 0}" ${locked ? "disabled" : ""}></td>`;
				}
				html += "</tr>";
			}
		}
		html += "</tbody></table></div>";
		this.$body.html(html);
		this.$body.find('input[data-some="1"]').each((_, el) => (el.indeterminate = true));
	}

	set(doctype, key, on) {
		const want = (this.want[doctype] = this.want[doctype] || {});
		want[key] = key === "confirm" ? (on ? "all" : "none") : on;
		if (key === "view" && !on) for (const [k] of SP_PM_COLS) if (k !== "view" && k !== "assigned") want[k] = k === "confirm" ? "none" : false;
		if (key !== "view" && on) want.view = true;
	}

	tick(el) {
		const dt = this.find(el.dataset.dt);
		if (dt[el.dataset.key] === null) return;
		this.set(el.dataset.dt, el.dataset.key, el.checked);
		this.render();
	}

	tick_module(el) {
		const m = this.data.modules.find((x) => x.module === el.dataset.module);
		for (const dt of m.doctypes) if (dt[el.dataset.key] !== null && dt[el.dataset.key] !== undefined) this.set(dt.doctype, el.dataset.key, el.checked);
		this.render();
	}

	find(doctype) {
		for (const m of this.data.modules) for (const dt of m.doctypes) if (dt.doctype === doctype) return dt;
	}

	changes() {
		const out = [];
		const doctypes = {};
		for (const [doctype, want] of Object.entries(this.want)) {
			const dt = this.find(doctype);
			const changed = {};
			for (const [key, value] of Object.entries(want)) {
				const before = key === "confirm" ? dt.confirm === "all" : !!dt[key];
				const after = key === "confirm" ? value === "all" : !!value;
				if (before !== after) {
					changed[key] = value;
					out.push(`${dt.label}: ${__(SP_PM_COLS.find((c) => c[0] === key)[1])} ${after ? "✓" : "✗"}`);
				}
			}
			if (Object.keys(changed).length) doctypes[doctype] = changed;
		}
		const fields = {};
		for (const f of this.data.fields) {
			if (f.key in this.fields && this.fields[f.key] !== (f.state === "all")) {
				fields[f.key] = this.fields[f.key];
				out.push(`${f.label} ${this.fields[f.key] ? "✓" : "✗"}`);
			}
		}
		return { out, doctypes, fields };
	}

	save() {
		if (!this.role || this.data.locked) return;
		const { out, doctypes, fields } = this.changes();
		if (!out.length) {
			frappe.show_alert(__("Nothing changed."));
			return;
		}
		const list = out.map((c) => `<li>${frappe.utils.escape_html(c)}</li>`).join("");
		frappe.confirm(`${__("Apply these changes to {0} now? Each one is recorded in the audit log.", [__(this.role)])}<ul>${list}</ul>`, async () => {
			const { message } = await frappe.call({ method: `${SP_PM}.save`, args: { role: this.role, doctypes, fields }, freeze: true });
			frappe.show_alert({ message: __("{0} changes saved.", [message.length]), indicator: "green" });
			this.load(this.role);
		});
	}

	new_role() {
		frappe.prompt({ fieldname: "role_name", fieldtype: "Data", label: __("Role Name"), reqd: 1 }, async ({ role_name: name }) => {
			const { message } = await frappe.call({ method: `${SP_PM}.new_role`, args: { name }, freeze: true });
			await this.refresh_roles(message);
		}, __("New Role"));
	}

	clone() {
		if (!this.role) return frappe.msgprint(__("Pick the role to clone first."));
		frappe.prompt({ fieldname: "role_name", fieldtype: "Data", label: __("New Role Name"), reqd: 1 }, async ({ role_name: name }) => {
			const { message } = await frappe.call({ method: `${SP_PM}.clone`, args: { source: this.role, name }, freeze: true });
			frappe.show_alert({ message: __("{0} made with {1} permissions.", [message.role, message.permissions]), indicator: "green" });
			await this.refresh_roles(message.role);
		}, __("Clone {0}", [__(this.role)]));
	}

	async preview() {
		if (!this.role) return frappe.msgprint(__("Pick a role first."));
		const { message } = await frappe.call(`${SP_PM}.preview`, { role: this.role });
		const groups = message.groups.map((g) => `<li><b>${frappe.utils.escape_html(g.group)}</b>: ${g.items.map(frappe.utils.escape_html).join("، ") || "—"}</li>`).join("");
		const add = message.new.map(frappe.utils.escape_html).join("، ") || "—";
		frappe.msgprint({ title: __("Menu of {0}", [__(this.role)]), message: `<ul>${groups}</ul><p><b>${__("+ New")}</b>: ${add}</p>` });
	}
}

frappe.dom.set_style(`
.sp-pm-fields { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-bottom: 12px; }
.sp-pm-table { overflow-x: auto; }
.sp-pm-table td, .sp-pm-table th { text-align: center; white-space: nowrap; }
.sp-pm-table td:first-child, .sp-pm-table th:first-child { text-align: start; }
.sp-pm-module td { background: var(--subtle-fg); }
.sp-pm-dt { padding-inline-start: 24px !important; }
.sp-pm-locked { color: var(--text-on-orange); }
`);
