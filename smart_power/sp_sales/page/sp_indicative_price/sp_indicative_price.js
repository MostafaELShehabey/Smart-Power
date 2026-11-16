// IP1 Indicative price (SP-49): a quick sale price for a walk-in or a caller, from the same
// template and engine as a quote (smart_power.sp_quotes.indicative). Nothing is saved as a quote
// and no cost is shown. "Make quote request" opens C3 with the type and specs; "Price check
// only" closes the enquiry as lost, so it still counts.

const SP_IP_API = "smart_power.sp_quotes.indicative";

frappe.pages["sp-indicative-price"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Indicative Price"), single_column: true });
	wrapper.sp_indicative = new SPIndicativePrice(page);
};

class SPIndicativePrice {
	constructor(page) {
		this.page = page;
		this.page.set_primary_action(__("Calculate"), () => this.calculate(), "calculator");
		this.$main = $('<div class="sp-indicative"></div>').appendTo(page.main);
		this.form = new frappe.ui.FieldGroup({
			parent: $("<div></div>").appendTo(this.$main),
			fields: [
				{
					fieldname: "system_type",
					fieldtype: "Link",
					options: "SP List Value",
					label: __("System Type"),
					reqd: 1,
					get_query: () => ({ filters: { list_name: "System Type", is_active: 1 } }),
					change: () => this.load_inputs(),
				},
			],
		});
		this.form.make();
		this.$inputs = $("<div></div>").appendTo(this.$main);
		this.$result = $('<div class="sp-indicative-result mt-3"></div>').appendTo(this.$main);
	}

	async load_inputs() {
		this.$inputs.empty();
		this.$result.empty();
		this.inputs = null;
		const system_type = this.form.get_value("system_type");
		if (!system_type) return;
		const { message: form } = await frappe.call(`${SP_IP_API}.indicative_form`, { system_type });
		if (!form.template) {
			this.$inputs.html(
				`<div class="text-muted">${frappe.utils.escape_html(
					__("There is no published calculation template for this system type.")
				)}</div>`
			);
			return;
		}
		this.inputs = new frappe.ui.FieldGroup({
			parent: this.$inputs,
			fields: form.inputs.map((i) => ({
				fieldname: i.input_key,
				fieldtype: i.input_type === "Check" ? "Check" : i.input_type,
				options: i.options,
				label: i.label, // the template's own words, in Arabic
				description: i.help,
				reqd: 1,
			})),
		});
		this.inputs.make();
	}

	async calculate() {
		const system_type = this.form.get_value("system_type");
		if (!system_type || !this.inputs) return;
		const values = this.inputs.get_values();
		if (!values) return;
		const { message: r } = await frappe.call({
			method: `${SP_IP_API}.indicative_price`,
			args: { system_type, inputs: values },
			freeze: true,
		});
		this.last = { system_type, inputs: values };
		this.render(r);
	}

	render(r) {
		const esc = frappe.utils.escape_html;
		const money = (v) => format_currency(v, frappe.boot.sysdefaults.currency);
		const stale = r.stale.length
			? `<span class="sp-stale-clock ms-2" title="${esc(
					__("Old price: {0}", [r.stale.map((s) => s.item_name).join("، ")])
			  )}">${frappe.utils.icon("clock", "md")}</span>`
			: "";
		const per_kw = r.price_per_kw
			? `<div class="text-muted">${esc(__("{0} per kW, for {1} kW", [money(r.price_per_kw), format_number(r.plant_kw, null, 2)]))}</div>` // sp-allow-number: kW to 2 decimals
			: "";
		const missing = r.missing.length
			? `<div class="text-warning small mt-2">${esc(__("Not priced yet: {0}", [r.missing.join("، ")]))}</div>`
			: "";
		this.$result.html(`<div class="frappe-card p-3">
			<div class="text-muted small">${esc(__("Indicative sale price"))}</div>
			<div class="d-flex align-items-center"><span class="sp-indicative-total">${esc(money(r.total_sell))}</span>${stale}</div>
			${per_kw}${missing}
			<div class="mt-3 sp-indicative-actions"></div></div>`);
		const $actions = this.$result.find(".sp-indicative-actions");
		$(`<button class="btn btn-primary btn-sm me-2"></button>`)
			.text(__("Make quote request"))
			.on("click", () => this.make_request())
			.appendTo($actions);
		$(`<button class="btn btn-default btn-sm"></button>`)
			.text(__("Price check only"))
			.on("click", () => this.price_check())
			.appendTo($actions);
	}

	make_request() {
		// C3 takes the type and specs; the server records the indicative price on the new case
		frappe.route_options = { system_type: this.last.system_type, indicative_inputs: this.last.inputs };
		frappe.set_route("sp-quote-request");
	}

	price_check() {
		const dialog = new frappe.ui.Dialog({
			title: __("Price check only"),
			fields: [
				{
					fieldname: "channel",
					fieldtype: "Select",
					label: __("Channel"),
					reqd: 1,
					options: [
						{ value: "Showroom", label: __("Showroom") },
						{ value: "Call", label: __("Call") },
						{ value: "Marketing", label: __("Marketing") },
					],
					default: "Showroom",
				},
				{
					fieldname: "mobile",
					fieldtype: "Data",
					label: __("Mobile"),
					description: __("Optional: for the conversion statistics."),
				},
				{ fieldname: "customer_name", fieldtype: "Data", label: __("Customer Name") },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			],
			primary_action_label: __("Close as price check"),
			primary_action: async (values) => {
				const { message: name } = await frappe.call({
					method: `${SP_IP_API}.price_check_only`,
					args: { system_type: this.last.system_type, inputs: this.last.inputs, ...values },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Closed as a price check: {0}", [name]), indicator: "green" });
				this.$result.empty();
			},
		});
		dialog.show();
	}
}
