// X8 Document numbering (SP-134): every numbered document, its format, this year's prefix,
// the current counter and the next number. The rules are on the server (sp_core/numbering.py).

const SP_NUM_API = "smart_power.sp_core.numbering";

frappe.pages["sp-numbering"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Document Numbering"),
		single_column: true,
	});
	wrapper.sp_numbering = new SPNumbering(page);
};

frappe.pages["sp-numbering"].on_page_show = function (wrapper) {
	wrapper.sp_numbering && wrapper.sp_numbering.refresh();
};

class SPNumbering {
	constructor(page) {
		this.page = page;
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.page.add_inner_button(__("Document Naming Settings"), () =>
			frappe.set_route("Form", "Document Naming Settings")
		);
		$(`<p class="text-muted"></p>`)
			.text(
				__(
					"Formats with .YYYY. restart every year. ERPNext documents change their format in Document Naming Settings."
				)
			)
			.appendTo(this.page.main);
		this.$body = $('<div class="sp-num-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	async refresh() {
		const { message: rows } = await frappe.call(`${SP_NUM_API}.get_numbering`);
		this.render(rows || []);
	}

	render(rows) {
		const esc = frappe.utils.escape_html;
		this.$body.empty();
		const $table = $(`<table class="table table-hover"><thead><tr>
			<th>${esc(__("Document"))}</th>
			<th>${esc(__("Format"))}</th>
			<th>${esc(__("This Year's Prefix"))}</th>
			<th class="text-right">${esc(__("Current"))}</th>
			<th>${esc(__("Next Number"))}</th>
			<th></th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$body);
		rows.forEach((r) => {
			const yearly = r.yearly
				? ` <span class="indicator-pill blue">${esc(__("Yearly reset"))}</span>`
				: "";
			const $row = $(`<tr>
				<td>${esc(r.label)}</td>
				<td><code>${esc(r.series)}</code>${yearly}</td>
				<td><code>${esc(r.prefix)}</code></td>
				<td class="text-right">${esc(String(r.current))}</td>
				<td><code>${esc(r.next)}</code></td>
				<td class="text-right"></td>
			</tr>`);
			$(`<button class="btn btn-xs btn-default"></button>`)
				.text(__("Set Counter"))
				.on("click", () => this.set_counter(r))
				.appendTo($row.find("td:last"));
			$table.find("tbody").append($row);
		});
	}

	set_counter(r) {
		const dialog = new frappe.ui.Dialog({
			title: __("Set Counter: {0}", [r.prefix]),
			fields: [
				{
					fieldname: "value",
					fieldtype: "Int",
					label: __("Counter"),
					default: r.current,
					reqd: 1,
					description: __("The next document gets this number plus one."),
				},
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await frappe.call({
					method: `${SP_NUM_API}.set_counter`,
					args: { doctype: r.doctype, series: r.series, ...values },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Counter saved"), indicator: "green" });
				this.refresh();
			},
		});
		dialog.show();
	}
}
