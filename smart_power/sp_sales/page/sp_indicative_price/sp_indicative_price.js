// IP1 Indicative price (SP-49): a quick sale price for a walk-in or a caller, from the same
// calculation template as a formal quote. Sale price only, never cost; nothing is saved as a
// quote. "Make Quote Request" carries the inputs into C3; "Price Check Only" closes the
// enquiry as lost. The rules are on the server (smart_power.sp_quotes.indicative and
// smart_power.sp_sales.price_check).

const SP_IP_API = "smart_power.sp_quotes.indicative";

frappe.pages["sp-indicative-price"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Indicative Price"),
		single_column: true,
	});
	wrapper.sp_indicative_price = new SPIndicativePrice(page);
};

class SPIndicativePrice {
	constructor(page) {
		this.page = page;
		this.page.set_primary_action(__("Calculate"), () => this.calculate(), "calculator");
		this.page.add_inner_button(__("Clear"), () => this.reset());
		this.$main = $('<div class="sp-indicative-price"></div>').appendTo(this.page.main);
		this.make();
	}

	make() {
		this.result = null;
		this.inputs = null;
		this.form = new frappe.ui.FieldGroup({
			parent: this.$main,
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
				{ fieldtype: "Column Break" },
				{
					fieldname: "tier",
					fieldtype: "Select",
					label: __("Tier"),
					options: [
						{ value: "Individual", label: __("Individual") },
						{ value: "Company", label: __("Company") },
					],
					default: "Individual",
					change: () => this.clear_result(),
				},
				{ fieldtype: "Section Break" },
				{ fieldtype: "HTML", fieldname: "inputs_area" },
				{ fieldtype: "Section Break" },
				{ fieldtype: "HTML", fieldname: "result_area" },
			],
		});
		this.form.make();
	}

	async load_inputs() {
		const token = (this.load_token = (this.load_token || 0) + 1);
		const area = this.form.get_field("inputs_area").$wrapper.empty();
		this.inputs = null;
		this.clear_result();
		const system_type = this.form.get_value("system_type");
		if (!system_type) return;
		const { message: r } = await frappe.call({
			method: `${SP_IP_API}.indicative_form`,
			args: { system_type },
		});
		if (!r || token !== this.load_token) return;
		area.empty();
		this.inputs = new frappe.ui.FieldGroup({
			parent: area,
			fields: r.inputs.map((f) => ({
				fieldname: f.input_key,
				fieldtype: f.input_type || "Data",
				label: __(f.label),
				options: f.options,
				reqd: f.reqd,
				description: f.help,
				change: () => this.clear_result(),
			})),
		});
		this.inputs.make();
	}

	async calculate() {
		const values = this.form.get_values();
		if (!values) return;
		const inputs = this.inputs ? this.inputs.get_values() : {};
		if (!inputs) return;
		const { message: r } = await frappe.call({
			method: `${SP_IP_API}.indicative_price`,
			args: { system_type: values.system_type, inputs, tier: values.tier },
			freeze: true,
			freeze_message: __("Calculating…"),
		});
		this.result = { ...r, system_type: values.system_type };
		this.render();
	}

	render() {
		const r = this.result;
		const esc = frappe.utils.escape_html;
		const area = this.form.get_field("result_area").$wrapper.empty();
		if (!r) return;
		// a clock when a price used is old; its tooltip names the items
		const stale = (r.stale_items || [])
			.map((s) => __("{0}: price is {1} days old", [s.item_name || s.item_code, s.age_days]))
			.join("\n");
		const clock = stale
			? `<span class="sp-ip-stale text-warning ml-2" title="${esc(stale)}" aria-label="${esc(stale)}">
				${frappe.utils.icon("es-line-time", "md")}</span>`
			: "";
		const per_kw =
			r.price_per_kw != null
				? `<div class="text-muted">${esc(__("Price per kW"))}: <b>${esc(
						format_currency(r.price_per_kw)
				  )}</b> · ${esc(__("{0} kW", [frappe.format(r.kw, { fieldtype: "Float" })]))}</div>`
				: "";
		const incomplete = (r.incomplete || []).length
			? `<div class="alert alert-warning small mt-3">${esc(
					__("Some lines have no price, so the total is low:")
			  )}<ul class="mb-0">${r.incomplete.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>`
			: "";
		const $card = $(`<div class="frappe-card p-4">
			<div class="text-muted small">${esc(__("Indicative sale price"))}</div>
			<div class="d-flex align-items-center">
				<h2 class="sp-ip-total mb-1">${esc(format_currency(r.total_sell))}</h2>${clock}
			</div>
			${per_kw}
			<div class="text-muted small mt-2">${esc(
				__("Not a quote: the formal quote is made from a quote request.")
			)}</div>
			${incomplete}
			<div class="mt-4 sp-ip-actions"></div>
		</div>`).appendTo(area);
		const $actions = $card.find(".sp-ip-actions");
		$(`<button class="btn btn-primary btn-sm mr-2"></button>`)
			.text(__("Make Quote Request"))
			.on("click", () => this.make_request())
			.appendTo($actions);
		$(`<button class="btn btn-default btn-sm"></button>`)
			.text(__("Price Check Only"))
			.on("click", () => this.price_check())
			.appendTo($actions);
	}

	make_request() {
		const r = this.result;
		frappe.route_options = {
			system_type: r.system_type,
			details: r.inputs,
			tier: r.tier,
			indicative_run: r.run,
		};
		frappe.set_route("sp-quote-request");
	}

	price_check() {
		const dialog = new frappe.ui.Dialog({
			title: __("Price Check Only"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted small">${frappe.utils.escape_html(
						__("The enquiry is closed as lost: price check only. Name and mobile are optional.")
					)}</p>`,
				},
				{
					fieldname: "channel",
					fieldtype: "Select",
					label: __("Channel"),
					reqd: 1,
					options: [
						{ value: "Call", label: __("Call") },
						{ value: "Showroom", label: __("Showroom") },
						{ value: "Marketing", label: __("Marketing") },
					],
					default: "Call",
				},
				{ fieldname: "mobile", fieldtype: "Data", label: __("Mobile") },
				{ fieldname: "customer_name", fieldtype: "Data", label: __("Customer Name") },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			],
			primary_action_label: __("Close as Price Check"),
			primary_action: async (values) => {
				const { message: r } = await frappe.call({
					method: "smart_power.sp_sales.price_check.close_price_check",
					args: { request: { ...values, tier: this.result.tier, run: this.result.run } },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Closed as price check: {0}", [r.case]), indicator: "green" });
				this.reset();
			},
		});
		dialog.show();
	}

	clear_result() {
		this.result = null;
		this.form && this.form.get_field("result_area").$wrapper.empty();
	}

	reset() {
		this.$main.empty();
		this.make();
	}
}
