// C3b Import leads (SP-51): upload an Excel or CSV file, map its columns, dry-run (new,
// duplicates, errors), then import in the background; each new row becomes my lead, tagged with
// the campaign. The rules are on the server (smart_power.sp_sales.lead_import).
const SP_LI_API = "smart_power.sp_sales.lead_import";
const SP_LI_LABELS = {
	lead_name: __("Name"),
	sp_mobile: __("Mobile"),
	company_name: __("Company"),
	city: __("City"),
	notes: __("Notes"),
};

frappe.pages["sp-import-leads"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Import Leads"), single_column: true });
	wrapper.sp_import = new SPImportLeads(page);
};

class SPImportLeads {
	constructor(page) {
		this.page = page;
		this.$main = $('<div class="sp-import-leads"></div>').appendTo(page.main);
		this.form = new frappe.ui.FieldGroup({
			parent: $("<div></div>").appendTo(this.$main),
			fields: [
				{
					fieldname: "campaign",
					fieldtype: "Link",
					options: "SP Campaign",
					label: __("Campaign"),
					get_query: () => ({ filters: { status: "Active" } }),
					description: __("Each imported lead is tagged with it."),
				},
				{ fieldtype: "Column Break" },
				{ fieldname: "file_html", fieldtype: "HTML" },
			],
		});
		this.form.make();
		this.$file = this.form.get_field("file_html").$wrapper;
		$(`<button class="btn btn-default btn-sm mt-4"></button>`)
			.text(__("Upload Excel or CSV"))
			.on("click", () => this.upload())
			.appendTo(this.$file);
		this.$mapping = $('<div class="mt-3"></div>').appendTo(this.$main);
		this.$result = $('<div class="mt-3"></div>').appendTo(this.$main);
	}

	upload() {
		new frappe.ui.FileUploader({
			allow_multiple: false,
			restrictions: { allowed_file_types: [".xlsx", ".csv"] },
			on_success: async (file) => {
				this.file_url = file.file_url;
				const { message: cols } = await frappe.call(`${SP_LI_API}.read_columns`, { file_url: file.file_url });
				this.render_mapping(file.file_name, cols);
			},
		});
	}

	render_mapping(file_name, cols) {
		const esc = frappe.utils.escape_html;
		this.$result.empty();
		this.$mapping.html(
			`<h6>${esc(__("{0}: {1} rows", [file_name, cols.rows]))}</h6><div class="text-muted small mb-2">${esc(
				__("Match each field to a column of the file.")
			)}</div>`
		);
		const options = [{ value: "", label: __("(none)") }].concat(
			cols.headers.map((h, i) => ({ value: String(i), label: h || __("Column {0}", [i + 1]) }))
		);
		this.mapping = new frappe.ui.FieldGroup({
			parent: $("<div></div>").appendTo(this.$mapping),
			fields: cols.fields.map((f) => ({
				fieldname: f,
				fieldtype: "Select",
				label: SP_LI_LABELS[f] || f,
				options,
				default: cols.mapping[f] !== undefined ? String(cols.mapping[f]) : "",
				reqd: ["lead_name", "sp_mobile"].includes(f) ? 1 : 0,
			})),
		});
		this.mapping.make();
		this.page.set_primary_action(__("Dry run"), () => this.dry_run());
	}

	values() {
		const mapping = this.mapping.get_values();
		if (!mapping) return null;
		return { file_url: this.file_url, mapping, campaign: this.form.get_value("campaign") || null };
	}

	async dry_run() {
		const args = this.values();
		if (!args) return;
		const { message: r } = await frappe.call({ method: `${SP_LI_API}.dry_run`, args, freeze: true });
		const esc = frappe.utils.escape_html;
		const list = (rows) =>
			rows
				.slice(0, 50) // sp-allow-number: the first rows of a long list
				.map((d) => `<li>${esc(__("Row {0}", [d.row]))} · ${esc(d.mobile || "")} · ${esc(d.message)}</li>`)
				.join("");
		this.$result.html(`<div class="frappe-card p-3">
			<div><b>${esc(__("{0} new", [r.new]))}</b> · ${esc(__("{0} duplicates", [r.duplicate_count]))} · ${esc(
				__("{0} errors", [r.error_count])
			)}</div>
			${r.duplicate_count ? `<div class="mt-2 small"><b>${esc(__("Duplicates"))}</b><ul>${list(r.duplicates)}</ul></div>` : ""}
			${r.error_count ? `<div class="mt-2 small text-danger"><b>${esc(__("Errors"))}</b><ul>${list(r.errors)}</ul></div>` : ""}
		</div>`);
		if (r.new) this.page.set_primary_action(__("Import {0} leads", [r.new]), () => this.start());
	}

	async start() {
		const args = this.values();
		if (!args) return;
		const { message: name } = await frappe.call({ method: `${SP_LI_API}.start`, args, freeze: true });
		this.page.clear_primary_action();
		this.follow(name);
	}

	// the job runs in the background: follow its SP Lead Import until it is done
	async follow(name) {
		const esc = frappe.utils.escape_html;
		const doc = await frappe.db.get_value(
			"SP Lead Import",
			name,
			["status", "new_count", "duplicate_count", "error_count", "result_file", "error"]
		);
		const d = doc.message;
		if (["Queued", "Running"].includes(d.status)) {
			this.$result.html(`<div class="text-muted">${esc(__("Importing… ({0})", [__(d.status)]))}</div>`);
			setTimeout(() => this.follow(name), 2000); // sp-allow-number: poll every 2 seconds
			return;
		}
		const ok = d.status === "Done";
		this.$result.html(`<div class="frappe-card p-3">
			<div class="${ok ? "text-success" : "text-danger"}"><b>${esc(__(d.status))}</b>
			${ok ? ` · ${esc(__("{0} leads created", [d.new_count]))} · ${esc(__("{0} duplicates", [d.duplicate_count]))} · ${esc(__("{0} errors", [d.error_count]))}` : ` · ${esc(d.error || "")}`}</div>
			${d.result_file ? `<a class="btn btn-default btn-xs mt-2" href="${encodeURI(d.result_file)}" target="_blank">${esc(__("Download the result"))}</a>` : ""}
			<a class="btn btn-default btn-xs mt-2" href="/app/lead?owner=${encodeURIComponent(frappe.session.user)}">${esc(__("Open my leads"))}</a>
		</div>`);
	}
}
