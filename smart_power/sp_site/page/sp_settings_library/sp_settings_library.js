// SET1 Settings library (SP-98): inverter parameter files per brand and model. Download the latest
// (or an older version from its history) and upload a new version with notes; old versions are
// kept. The rules are on the server (smart_power.sp_site.settings_files).
const SP_SET_API = "smart_power.sp_site.settings_files";
const SP_SET_DOCTYPE = "SP Settings File";

frappe.pages["sp-settings-library"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Settings Library"), single_column: true });
	wrapper.sp_settings = new SPSettingsLibrary(page);
};

class SPSettingsLibrary {
	constructor(page) {
		this.page = page;
		this.can_upload = frappe.model.can_create(SP_SET_DOCTYPE);
		this.$main = $('<div class="sp-settings-library"></div>').appendTo(page.main);
		this.brand = page.add_field({
			fieldname: "brand",
			label: __("Inverter Brand"),
			fieldtype: "Link",
			options: "SP List Value",
			get_query: () => ({ filters: { list_name: "Inverter Brand", is_active: 1 } }),
			change: () => this.refresh(),
		});
		this.search = page.add_field({
			fieldname: "search",
			label: __("Search model or notes"),
			fieldtype: "Data",
			change: () => this.refresh(),
		});
		if (this.can_upload) {
			page.set_primary_action(__("Upload New Version"), () => this.upload_dialog(), "upload");
		}
		this.refresh();
	}

	async refresh() {
		const { message: rows } = await frappe.call(`${SP_SET_API}.library`, {
			brand: this.brand.get_value() || null,
			search: this.search.get_value() || null,
		});
		this.render(rows);
	}

	render(rows) {
		const esc = frappe.utils.escape_html;
		this.$main.empty();
		if (!rows.length) {
			this.$main.html(`<div class="text-muted">${esc(__("No settings files yet."))}</div>`);
			return;
		}
		const $table = $(`<table class="table table-bordered table-sm bg-white">
			<thead><tr>
				<th>${esc(__("Inverter Brand"))}</th><th>${esc(__("Model"))}</th><th>${esc(__("Latest"))}</th>
				<th>${esc(__("Uploaded"))}</th><th>${esc(__("Notes"))}</th><th></th>
			</tr></thead><tbody></tbody></table>`).appendTo(this.$main);
		rows.forEach((r) => {
			const $tr = $(`<tr>
				<td class="sp-set-brand"></td><td class="sp-set-model"></td><td class="sp-set-version"></td>
				<td class="sp-set-date"></td><td class="sp-set-notes small"></td>
				<td class="text-nowrap"><a class="btn btn-default btn-xs mr-1 sp-set-download"></a></td>
			</tr>`).appendTo($table.find("tbody"));
			$tr.find(".sp-set-brand").text(r.brand_label);
			$tr.find(".sp-set-model").text(r.model);
			$tr.find(".sp-set-version").text(`v${r.version}`);
			$tr.find(".sp-set-date").text(`${frappe.datetime.str_to_user(r.creation)} · ${frappe.user.full_name(r.uploaded_by)}`);
			$tr.find(".sp-set-notes").text(r.notes || "");
			$tr.find(".sp-set-download").attr({ href: r.file, download: "" }).text(__("Download"));
			const $actions = $tr.find("td:last");
			if (r.versions > 1) {
				$('<button class="btn btn-default btn-xs mr-1"></button>')
					.text(__("History ({0})", [r.versions]))
					.on("click", () => this.history(r))
					.appendTo($actions);
			}
			if (this.can_upload) {
				$('<button class="btn btn-default btn-xs"></button>')
					.text(__("New Version"))
					.on("click", () => this.upload_dialog(r))
					.appendTo($actions);
			}
		});
	}

	async history(r) {
		const esc = frappe.utils.escape_html;
		const { message: versions } = await frappe.call(`${SP_SET_API}.history`, { brand: r.brand, model: r.model });
		const d = new frappe.ui.Dialog({ title: `${r.brand_label} ${r.model}`, size: "large" });
		const $list = $('<div></div>').appendTo(d.body);
		versions.forEach((v) => {
			const $row = $(`<div class="d-flex align-items-start border-bottom py-2">
				<div class="mr-3"><b class="sp-v"></b><div class="text-muted small sp-when"></div></div>
				<div class="flex-grow-1 small sp-notes"></div>
				<a class="btn btn-default btn-xs ml-2"></a>
			</div>`).appendTo($list);
			$row.find(".sp-v").text(`v${v.version}${v.is_latest ? ` · ${__("Latest")}` : ""}`);
			$row.find(".sp-when").text(`${frappe.datetime.str_to_user(v.creation)} · ${frappe.user.full_name(v.uploaded_by)}`);
			$row.find(".sp-notes").text(v.notes || "");
			$row.find("a").attr({ href: v.file, download: "" }).text(__("Download"));
		});
		if (!versions.length) $list.html(`<div class="text-muted">${esc(__("No versions."))}</div>`);
		d.show();
	}

	upload_dialog(r) {
		const d = new frappe.ui.Dialog({
			title: __("Upload New Version"),
			fields: [
				{
					fieldname: "brand",
					label: __("Inverter Brand"),
					fieldtype: "Link",
					options: "SP List Value",
					reqd: 1,
					default: r?.brand,
					hidden: !!r,
					get_query: () => ({ filters: { list_name: "Inverter Brand", is_active: 1 } }),
				},
				// a new version of a listed model shows its brand by name
				{
					fieldname: "brand_label",
					label: __("Inverter Brand"),
					fieldtype: "Data",
					read_only: 1,
					default: r?.brand_label,
					hidden: !r,
				},
				{ fieldname: "model", label: __("Model"), fieldtype: "Data", reqd: 1, default: r?.model, read_only: !!r },
				{
					fieldname: "file_url",
					label: __("Settings File"),
					fieldtype: "Attach",
					reqd: 1,
				},
				{ fieldname: "notes", label: __("Notes"), fieldtype: "Small Text", description: __("What changed in this version.") },
			],
			primary_action_label: __("Upload"),
			primary_action: async (values) => {
				const { brand, model, file_url, notes } = values;
				const { message: v } = await frappe.call({
					method: `${SP_SET_API}.upload`,
					args: { brand, model, file_url, notes },
					freeze: true,
				});
				d.hide();
				frappe.show_alert({ message: __("{0} uploaded.", [v.title]), indicator: "green" });
				this.refresh();
			},
		});
		d.show();
	}
}
