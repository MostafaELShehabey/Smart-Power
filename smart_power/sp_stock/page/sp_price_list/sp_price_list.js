// I2 Price List (SP-30): one row per item with List Price, P1 Cost, BTB, BTC, their dates and
// the price-age chip. Cost columns come from the server only for cost roles (SP-35): for everyone
// else the values are never sent, so the columns are not drawn.
// Pricing managers click a price to change it; a change needs a reason, and the category's
// pricing rules update the prices worked out from it. The rules live on the server
// (smart_power.sp_stock.prices and price_list_api).

const SP_PRICE_API = "smart_power.sp_stock.price_list_api";
const SP_PAGE_LENGTH = 100; // sp-allow-number: rows per "load more", not a business value

const SP_AGE_CHIP = {
	fresh: { color: "green", label: __("Fresh") },
	aging: { color: "orange", label: __("Aging") },
	stale: { color: "red", label: __("Stale") },
	no_limit: { color: "gray", label: __("No limit") },
	no_price: { color: "gray", label: __("No price") },
};

// key → [column label, value field, date field, supplier field]
const SP_PRICE_COLUMNS = [
	["list", __("List Price"), "list_price", "list_date", "list_supplier"],
	["cost", __("P1 Cost"), "cost", "cost_date", "cost_supplier"],
	["btb", __("BTB"), "btb", "btb_date", null],
	["btc", __("BTC"), "btc", "btc_date", null],
];

frappe.pages["sp-price-list"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Price List"),
		single_column: true,
	});
	wrapper.sp_price_list = new SPPriceList(page);
};

frappe.pages["sp-price-list"].on_page_show = function (wrapper) {
	wrapper.sp_price_list && wrapper.sp_price_list.refresh();
};

class SPPriceList {
	constructor(page) {
		this.page = page;
		this.rows = [];
		this.start = 0;
		this.make_filters();
		this.$body = $('<div class="sp-price-list"></div>').appendTo(this.page.main);
		this.page.add_inner_button(__("Stale first"), () => {
			this.stale_first = !this.stale_first;
			this.refresh();
		});
		this.refresh();
	}

	make_filters() {
		const on_change = frappe.utils.debounce(() => this.refresh(), 300); // sp-allow-number: typing delay in ms
		this.filters = {
			search: this.page.add_field({ fieldname: "search", fieldtype: "Data", label: __("Code or name"), change: on_change }),
			item_group: this.page.add_field({ fieldname: "item_group", fieldtype: "Link", options: "Item Group", label: __("Item Group"), change: on_change }),
			sp_price_age_category: this.page.add_field({ fieldname: "sp_price_age_category", fieldtype: "Link", options: "SP Price Category", label: __("Price Category"), change: on_change }),
			brand: this.page.add_field({ fieldname: "brand", fieldtype: "Link", options: "Brand", label: __("Brand"), change: on_change }),
			age_status: this.page.add_field({
				fieldname: "age_status",
				fieldtype: "Select",
				label: __("Age"),
				options: [""].concat(Object.keys(SP_AGE_CHIP)).map((value) => ({ value, label: value ? SP_AGE_CHIP[value].label : "" })),
				change: on_change,
			}),
		};
	}

	filter_values() {
		const values = { stale_first: this.stale_first ? 1 : 0 };
		Object.entries(this.filters).forEach(([key, field]) => {
			const value = field.get_value();
			if (value) values[key] = value;
		});
		return values;
	}

	async refresh(more = false) {
		this.start = more ? this.start + SP_PAGE_LENGTH : 0;
		const { message } = await frappe.call(`${SP_PRICE_API}.get_rows`, {
			filters: this.filter_values(),
			start: this.start,
			page_length: SP_PAGE_LENGTH,
		});
		this.meta = message;
		this.rows = more ? this.rows.concat(message.rows) : message.rows;
		this.render();
	}

	columns() {
		return SP_PRICE_COLUMNS.filter(([key]) => this.meta.sees_cost || ["btb", "btc"].includes(key));
	}

	render() {
		const columns = this.columns();
		const head = [__("Code"), __("Name"), __("Price Category")]
			.concat(columns.map((c) => c[1]))
			.concat(this.meta.sees_cost ? [__("Margin %")] : [])
			.concat([__("Age"), ""]);
		const $table = $(`<table class="table table-bordered table-hover sp-price-table">
			<thead><tr>${head.map((h) => `<th>${frappe.utils.escape_html(h)}</th>`).join("")}</tr></thead>
			<tbody></tbody></table>`);
		const $tbody = $table.find("tbody");
		this.rows.forEach((row) => $tbody.append(this.render_row(row, columns)));
		this.$body.empty().append($table);
		if (!this.rows.length) {
			this.$body.append(`<p class="text-muted">${__("No items match these filters.")}</p>`);
		}
		if (this.rows.length < this.meta.total) {
			$(`<button class="btn btn-default btn-sm">${__("Load more")}</button>`)
				.on("click", () => this.refresh(true))
				.appendTo(this.$body);
		}
		this.$body.append(
			`<p class="text-muted small">${__("{0} of {1} items", [this.rows.length, this.meta.total])}</p>`
		);
	}

	render_row(row, columns) {
		const $tr = $("<tr></tr>").attr("data-item", row.item_code);
		$tr.append(`<td><a href="/desk/item/${encodeURIComponent(row.item_code)}">${frappe.utils.escape_html(row.item_code)}</a></td>`);
		$tr.append(`<td>${frappe.utils.escape_html(row.sp_name_ar || row.item_name || "")}</td>`);
		$tr.append(`<td>${frappe.utils.escape_html(row.category || "")}</td>`);
		columns.forEach(([key, _label, value_field, date_field, supplier_field]) => {
			const $td = $('<td class="sp-price-cell"></td>');
			const value = row[value_field];
			$td.append(`<div><bdi>${value == null ? "–" : format_currency(value)}</bdi></div>`);
			// date and supplier on their own lines, isolated so Latin names do not jumble the RTL line
			if (row[date_field]) {
				$td.append(`<div class="text-muted small"><bdi>${frappe.datetime.str_to_user(row[date_field])}</bdi></div>`);
			}
			if (supplier_field && row[supplier_field]) {
				$td.append(`<div class="text-muted small"><bdi>${frappe.utils.escape_html(row[supplier_field])}</bdi></div>`);
			}
			if (this.meta.can_edit) {
				$td.addClass("sp-editable").attr("title", __("Click to change")).on("click", () => this.edit_price(row, key));
			}
			$tr.append($td);
		});
		if (this.meta.sees_cost) {
			$tr.append(`<td>${row.margin_pct == null ? "–" : frappe.utils.escape_html(String(row.margin_pct)) + "%"}</td>`);
		}
		const chip = SP_AGE_CHIP[row.age_status] || SP_AGE_CHIP.no_price;
		const clock = row.age_status === "stale" ? `${frappe.utils.icon("es-line-time", "xs")} ` : "";
		const days = row.age_days == null ? "" : ` · ${__("{0} days", [row.age_days])}`;
		$tr.append(`<td><span class="indicator-pill ${chip.color}">${clock}${chip.label}${days}</span></td>`);
		const $actions = $("<td></td>");
		$(`<button class="btn btn-xs btn-default">${__("History")}</button>`)
			.on("click", () => this.show_history(row))
			.appendTo($actions);
		$tr.append($actions);
		return $tr;
	}

	edit_price(row, key) {
		const [, label, value_field, , supplier_field] = SP_PRICE_COLUMNS.find((c) => c[0] === key);
		const current = row[value_field];
		const cost_side = ["list", "cost"].includes(key);
		const dialog = new frappe.ui.Dialog({
			title: __("{0}: {1}", [row.item_code, label]),
			fields: [
				{ fieldname: "rate", fieldtype: "Currency", label: __("New price"), reqd: 1, default: current },
				{ fieldname: "price_date", fieldtype: "Date", label: __("Price date"), reqd: 1, default: frappe.datetime.get_today() },
				{
					fieldname: "supplier",
					fieldtype: "Link",
					options: "Supplier",
					label: __("Supplier"),
					hidden: cost_side ? 0 : 1,
					default: cost_side ? row[supplier_field] : null,
				},
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Reason"),
					reqd: current == null ? 0 : 1,
					description: current == null ? "" : __("Old price: {0}", [format_currency(current)]),
				},
				{
					fieldname: "apply_rules",
					fieldtype: "Check",
					label: __("Update the prices worked out from this one (pricing rules)"),
					default: 1,
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				const { message } = await frappe.call({
					method: `${SP_PRICE_API}.update_prices`,
					type: "POST",
					args: {
						item_code: row.item_code,
						values: { [key]: values.rate },
						reason: values.reason,
						supplier: values.supplier,
						price_date: values.price_date,
						apply_rules: values.apply_rules,
					},
					freeze: true,
				});
				dialog.hide();
				Object.assign(row, message.row);
				this.render();
				const derived = Object.keys(message.derived || {});
				frappe.show_alert({
					message: derived.length ? __("Saved. Also updated: {0}", [derived.join(", ").toUpperCase()]) : __("Saved"),
					indicator: "green",
				});
			},
		});
		dialog.show();
	}

	async show_history(row) {
		const { message } = await frappe.call(`${SP_PRICE_API}.price_history`, { item_code: row.item_code });
		const lines = (message || []).map(
			(e) => `<tr>
				<td>${frappe.datetime.str_to_user(e.at)}</td>
				<td>${frappe.utils.escape_html(e.user_name || e.user)}</td>
				<td><bdi>${frappe.utils.escape_html(e.price_list_label)}</bdi>${e.supplier ? ` · <bdi>${frappe.utils.escape_html(e.supplier)}</bdi>` : ""}</td>
				<td><bdi>${e.old == null ? "" : format_currency(e.old)}</bdi></td>
				<td><bdi>${format_currency(e.new)}</bdi></td>
				<td>${frappe.utils.escape_html(e.reason || "")}</td>
			</tr>`
		);
		const dialog = new frappe.ui.Dialog({ title: __("Price history: {0}", [row.item_code]), size: "large" });
		dialog.$body.html(
			lines.length
				? `<table class="table table-bordered"><thead><tr>
					<th>${__("When")}</th><th>${__("Who")}</th><th>${__("Price")}</th><th>${__("Old Value")}</th><th>${__("New Value")}</th><th>${__("Reason")}</th>
					</tr></thead><tbody>${lines.join("")}</tbody></table>`
				: `<p class="text-muted">${__("No price changes yet.")}</p>`
		);
		dialog.show();
	}
}
