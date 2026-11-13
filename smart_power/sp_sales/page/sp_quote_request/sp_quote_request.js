// C3 Quote request (SP-47): system type first, then only that type's fields; the mobile
// finds a returning customer instead of making a duplicate. Saving opens the case.
// The rules are on the server (smart_power.sp_sales.quote_request).

const SP_QR_API = "smart_power.sp_sales.quote_request";

frappe.pages["sp-quote-request"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Quote Request"),
		single_column: true,
	});
	wrapper.sp_quote_request = new SPQuoteRequest(page);
};

class SPQuoteRequest {
	constructor(page) {
		this.page = page;
		this.existing = null;
		this.page.set_primary_action(__("Save Request"), () => this.save(), "save");
		this.page.add_inner_button(__("Clear"), () => this.reset());
		this.$main = $('<div class="sp-quote-request"></div>').appendTo(this.page.main);
		this.make();
	}

	async make() {
		const { message: owners } = await frappe.call(`${SP_QR_API}.followup_owners`);
		const me = (owners || []).find((u) => u.name === frappe.session.user);
		this.form = new frappe.ui.FieldGroup({
			parent: this.$main,
			fields: [
				{ fieldtype: "Section Break", label: __("System Type") },
				{
					fieldname: "system_type",
					fieldtype: "Link",
					options: "SP List Value",
					label: __("System Type"),
					reqd: 1,
					get_query: () => ({ filters: { list_name: "System Type", is_active: 1 } }),
					change: () => this.load_request_fields(),
				},
				{ fieldtype: "HTML", fieldname: "details_area" },
				{ fieldtype: "Section Break", label: __("Location and Payment") },
				{ fieldname: "location_text", fieldtype: "Data", label: __("Location") },
				{
					fieldname: "payment_method",
					fieldtype: "Link",
					options: "SP List Value",
					label: __("Payment Method"),
					get_query: () => ({ filters: { list_name: "Financing Type", is_active: 1 } }),
				},
				{ fieldtype: "Column Break" },
				{ fieldname: "geo", fieldtype: "Geolocation", label: __("Location Pin") },
				{ fieldtype: "Section Break", label: __("Customer") },
				{
					fieldname: "mobile",
					fieldtype: "Data",
					label: __("Mobile"),
					reqd: 1,
					change: () => this.check_mobile(),
				},
				{ fieldtype: "HTML", fieldname: "customer_status" },
				{ fieldname: "customer_name", fieldtype: "Data", label: __("Customer Name") },
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
				},
				{
					fieldname: "region",
					fieldtype: "Link",
					options: "SP List Value",
					label: __("Region"),
					get_query: () => ({ filters: { list_name: "Region", is_active: 1 } }),
				},
				{ fieldtype: "Section Break", label: __("Case") },
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
				{
					fieldname: "follow_up_owner",
					fieldtype: "Select",
					label: __("Follow-up Owner"),
					reqd: 1,
					options: (owners || []).map((u) => ({ value: u.name, label: u.full_name || u.name })),
					default: me ? me.name : undefined,
				},
				{ fieldtype: "Column Break" },
				{ fieldname: "site_visit_needed", fieldtype: "Check", label: __("Site Visit Needed") },
				{ fieldname: "request_notes", fieldtype: "Small Text", label: __("Request Notes") },
			],
		});
		this.form.make();
		this.details = null;
	}

	async load_request_fields() {
		const area = this.form.get_field("details_area").$wrapper.empty();
		this.details = null;
		const system_type = this.form.get_value("system_type");
		if (!system_type) return;
		const { message: fields } = await frappe.call(`${SP_QR_API}.get_request_fields`, { system_type });
		if (!fields || !fields.length) return;
		const arabic = frappe.boot.lang === "ar";
		const label = (f) => (arabic && f.label_ar ? f.label_ar : __(f.label || f.fieldname));
		this.details = new frappe.ui.FieldGroup({
			parent: area,
			fields: fields.map((f) =>
				f.fieldtype === "Load Table"
					? {
							fieldname: "loads",
							fieldtype: "Table",
							label: label(f),
							reqd: f.reqd,
							in_place_edit: true,
							data: [],
							fields: [
								{ fieldname: "device", fieldtype: "Data", label: __("Device"), in_list_view: 1, reqd: 1 },
								{ fieldname: "qty", fieldtype: "Int", label: __("Qty"), in_list_view: 1, default: 1 },
								{ fieldname: "watts", fieldtype: "Float", label: __("Watts"), in_list_view: 1 },
								{ fieldname: "day_hours", fieldtype: "Float", label: __("Day Hours"), in_list_view: 1 },
								{ fieldname: "night_hours", fieldtype: "Float", label: __("Night Hours"), in_list_view: 1 },
							],
					  }
					: {
							fieldname: f.fieldname,
							fieldtype: f.fieldtype,
							options: f.options,
							reqd: f.reqd,
							label: label(f),
					  }
			),
		});
		this.details.make();
	}

	async check_mobile() {
		const mobile = this.form.get_value("mobile");
		const status = this.form.get_field("customer_status").$wrapper.empty();
		this.existing = null;
		this.blocked = false;
		this.toggle_new_customer(true);
		if (!mobile) return;
		const { message: r } = await frappe.call(`${SP_QR_API}.check_mobile`, { mobile });
		const esc = frappe.utils.escape_html;
		if (r.status === "invalid") {
			status.html(`<div class="text-danger small">${esc(__("This is not a valid Egyptian mobile."))}</div>`);
			return;
		}
		if (r.status === "colleague") {
			// a colleague's customer: only the owner's name, and a request to the admin
			this.blocked = true;
			this.toggle_new_customer(false);
			const $box = $(
				`<div class="alert alert-warning">${esc(__("Registered with {0}", [r.owner_name]))} </div>`
			).appendTo(status);
			$(`<button class="btn btn-xs btn-default"></button>`)
				.text(__("Ask the admin to reassign"))
				.on("click", async () => {
					await frappe.call({ method: `${SP_QR_API}.request_reassign`, args: { mobile } });
					frappe.show_alert({ message: __("The admin has been asked"), indicator: "green" });
				})
				.appendTo($box);
			return;
		}
		if (r.customer) {
			this.existing = r;
			this.toggle_new_customer(false);
			status.html(
				`<div class="alert alert-warning">${esc(__("Customer already exists"))}: ` +
					`<a href="/app/customer/${encodeURIComponent(r.customer)}" target="_blank">${esc(
						r.customer_name
					)}</a> · ${esc(__("Open cases: {0}", [r.open_cases]))}</div>`
			);
		}
	}

	toggle_new_customer(show) {
		for (const name of ["customer_name", "tier", "region"]) {
			this.form.set_df_property(name, "hidden", show ? 0 : 1);
		}
	}

	async save() {
		if (this.blocked) {
			frappe.msgprint(__("This customer is followed up by a colleague. Ask the admin to reassign them."));
			return;
		}
		const values = this.form.get_values();
		if (!values) return;
		const details = this.details ? this.details.get_values() : {};
		if (this.details && !details) return;
		const loads = (details.loads || []).map((row) => ({
			device: row.device,
			qty: row.qty,
			watts: row.watts,
			day_hours: row.day_hours,
			night_hours: row.night_hours,
		}));
		delete details.loads;
		const { message: r } = await frappe.call({
			method: `${SP_QR_API}.create_quote_request`,
			args: { request: { ...values, details, loads } },
			freeze: true,
			freeze_message: __("Saving the request…"),
		});
		frappe.show_alert({ message: __("Request {0} saved", [r.case]), indicator: "green" });
		frappe.set_route("Form", "SP Case", r.case);
	}

	reset() {
		this.$main.empty();
		this.existing = null;
		this.make();
	}
}
