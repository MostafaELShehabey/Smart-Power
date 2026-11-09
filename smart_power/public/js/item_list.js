// Item list (SP-29): "Import from Excel" for the catalog manager and the admin.
// ERPNext's own list settings load first and are kept. The import runs on the server.
(() => {
	const API = "smart_power.sp_stock.item_import";
	const settings = (frappe.listview_settings["Item"] = frappe.listview_settings["Item"] || {});
	const erpnext_onload = settings.onload;

	settings.onload = function (listview) {
		if (erpnext_onload) erpnext_onload.call(this, listview);
		if (!frappe.model.can_create("Item")) return;
		listview.page.add_inner_button(__("Import from Excel"), () => open_import_dialog(listview));
	};

	function open_import_dialog(listview) {
		const esc = frappe.utils.escape_html;
		const dialog = new frappe.ui.Dialog({
			title: __("Import Items from Excel"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "help",
					options: `<p>${esc(
						__("One row per item. A code that already exists updates that item; blank cells keep the old value.")
					)}</p><p><a href="/api/method/${API}.get_import_template">${esc(
						__("Download the template")
					)}</a></p>`,
				},
				{ fieldtype: "Attach", fieldname: "file", label: __("Excel File"), reqd: 1 },
				{ fieldtype: "HTML", fieldname: "result" },
			],
			primary_action_label: __("Import"),
			primary_action: async (values) => {
				const { message: r } = await frappe.call({
					method: `${API}.import_items`,
					args: { file_url: values.file },
					freeze: true,
					freeze_message: __("Importing items…"),
				});
				const rows = (r.rows || [])
					.filter((row) => row.status === "Error")
					.map(
						(row) =>
							`<tr><td>${row.row}</td><td>${esc(row.item_code || "")}</td><td>${esc(
								row.message
							)}</td></tr>`
					)
					.join("");
				const summary = __("Created: {0} · Updated: {1} · Errors: {2}", [r.created, r.updated, r.errors]); // sp-allow-number: placeholders
				dialog.fields_dict.result.$wrapper.html(
					`<p>${esc(summary)}</p>` +
						(rows
							? `<table class="table table-bordered"><thead><tr><th>${esc(__("Row"))}</th><th>${esc(
									__("Code")
							  )}</th><th>${esc(__("Error"))}</th></tr></thead><tbody>${rows}</tbody></table>`
							: "")
				);
				listview.refresh();
			},
		});
		dialog.show();
	}
})();
