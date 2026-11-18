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
		// one template per item group, with its coding scheme and cleansing (SP-165)
		listview.page.add_inner_button(__("Import by Group"), () => open_group_dialog(listview));
		// each pump's performance curve (SP-184)
		listview.page.add_inner_button(__("Import Pump Curves"), () => open_curve_dialog(listview));
	};

	function open_curve_dialog(listview) {
		const esc = frappe.utils.escape_html;
		const CURVES = "smart_power.sp_stock.pump_curve_import";
		const dialog = new frappe.ui.Dialog({
			title: __("Import Pump Curves"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "help",
					options: `<p>${esc(
						__("One row per curve point. The rows of a pump replace its curve.")
					)}</p><p><a href="/api/method/${CURVES}.get_import_template">${esc(__("Download the template"))}</a></p>`,
				},
				{ fieldtype: "Attach", fieldname: "file", label: __("Excel File"), reqd: 1 },
				{ fieldtype: "HTML", fieldname: "result" },
			],
			primary_action_label: __("Check"),
			primary_action: (values) => run(values, 1),
			secondary_action_label: __("Import"),
			secondary_action: () => {
				const values = dialog.get_values();
				if (values) run(values, 0);
			},
		});
		async function run(values, dry_run) {
			const { message: r } = await frappe.call({
				method: `${CURVES}.import_curves`,
				args: { file_url: values.file, dry_run },
				freeze: true,
				freeze_message: dry_run ? __("Checking…") : __("Importing curves…"),
			});
			const colour = { Error: "red", Skipped: "orange" };
			const rows = (r.rows || [])
				.filter((row) => row.status !== "OK")
				.map(
					(row) =>
						`<tr><td>${row.row}</td><td>${esc(row.item_code || "")}</td><td><span class="indicator-pill ${
							colour[row.status]
						}">${esc(__(row.status))}</span></td><td>${esc(row.message)}</td></tr>`
				)
				.join("");
			const counts = [r.pumps, r.points, r.errors, r.skipped];
			const summary = dry_run
				? __("Ready: {0} pumps, {1} points · Errors: {2} · Skipped: {3}", counts) // sp-allow-number: placeholders
				: __("Imported: {0} pumps, {1} points · Errors: {2} · Skipped: {3}", counts); // sp-allow-number: placeholders
			dialog.fields_dict.result.$wrapper.html(
				`<p><b>${esc(summary)}</b></p>` +
					(rows
						? `<table class="table table-bordered table-sm"><thead><tr><th>${esc(__("Row"))}</th><th>${esc(
								__("Code")
						  )}</th><th>${esc(__("Status"))}</th><th>${esc(__("Note"))}</th></tr></thead><tbody>${rows}</tbody></table>`
						: "")
			);
			if (!dry_run) listview.refresh();
		}
		dialog.show();
	}

	function open_group_dialog(listview) {
		const esc = frappe.utils.escape_html;
		const CODES = "smart_power.sp_stock.item_codes";
		const dialog = new frappe.ui.Dialog({
			title: __("Import Items by Group"),
			fields: [
				{
					fieldtype: "Link",
					fieldname: "item_group",
					options: "Item Group",
					label: __("Item Group"),
					reqd: 1,
					get_query: () => ({ filters: { is_group: 0 } }),
					change() {
						const group = dialog.get_value("item_group");
						dialog.fields_dict.template.$wrapper.html(
							group
								? `<a href="/api/method/${CODES}.get_group_template?item_group=${encodeURIComponent(group)}">${esc(
										__("Download the template of {0}", [group])
								  )}</a><p class="text-muted small">${esc(
										__("Leave the code empty: it is made from the group, the brand and the model.")
								  )}</p>`
								: ""
						);
					},
				},
				{ fieldtype: "HTML", fieldname: "template" },
				{ fieldtype: "Attach", fieldname: "file", label: __("Excel File"), reqd: 1 },
				{ fieldtype: "HTML", fieldname: "result" },
			],
			primary_action_label: __("Check"),
			primary_action: (values) => run(values, 1),
			secondary_action_label: __("Import"),
			secondary_action: () => {
				const values = dialog.get_values();
				if (values) run(values, 0);
			},
		});
		async function run(values, dry_run) {
			const { message: r } = await frappe.call({
				method: `${CODES}.import_group`,
				args: { file_url: values.file, item_group: values.item_group, dry_run },
				freeze: true,
				freeze_message: dry_run ? __("Checking…") : __("Importing items…"),
			});
			const colour = { OK: "green", Duplicate: "orange", Error: "red" };
			const rows = (r.rows || [])
				.filter((row) => row.status !== "OK" || !dry_run)
				.map(
					(row) =>
						`<tr><td>${row.row}</td><td>${esc(row.item_code || "")}</td><td><span class="indicator-pill ${
							colour[row.status] || "gray"
						}">${esc(__(row.status))}</span></td><td>${esc((row.messages || []).join(" "))}</td></tr>`
				)
				.join("");
			const summary = dry_run
				? __("Ready: {0} · Duplicates: {1} · Errors: {2}", [r.ok, r.duplicates, r.errors]) // sp-allow-number: placeholders
				: __("Imported: {0} · Duplicates: {1} · Errors: {2}", [r.imported, r.duplicates, r.errors]); // sp-allow-number: placeholders
			dialog.fields_dict.result.$wrapper.html(
				`<p><b>${esc(summary)}</b></p>` +
					(rows
						? `<table class="table table-bordered table-sm"><thead><tr><th>${esc(__("Row"))}</th><th>${esc(
								__("Code")
						  )}</th><th>${esc(__("Status"))}</th><th>${esc(__("Note"))}</th></tr></thead><tbody>${rows}</tbody></table>`
						: "")
			);
			if (!dry_run) listview.refresh();
		}
		dialog.show();
	}

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
