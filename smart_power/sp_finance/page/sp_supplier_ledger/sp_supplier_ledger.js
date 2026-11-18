// P5 Supplier ledger (SP-86): the running balance, what each station owes, what falls due, and paying
// the supplier. The rules are on the server (smart_power.sp_finance.supplier_ledger, supplier_payment).
const SP_SL_API = "smart_power.sp_finance.supplier_ledger";
const SP_SP_API = "smart_power.sp_finance.supplier_payment";

frappe.pages["sp-supplier-ledger"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Supplier Ledger"), single_column: true });
	wrapper.sp_ledger = new SPSupplierLedger(page);
};

frappe.pages["sp-supplier-ledger"].on_page_show = function (wrapper) {
	wrapper.sp_ledger?.show();
};

class SPSupplierLedger {
	constructor(page) {
		this.page = page;
		this.supplier = page.add_field({
			fieldname: "supplier",
			fieldtype: "Link",
			options: "Supplier",
			label: __("Supplier"),
			change: () => this.refresh(),
		});
		this.from_date = page.add_field({ fieldname: "from_date", fieldtype: "Date", label: __("From Date"), change: () => this.refresh() });
		this.to_date = page.add_field({ fieldname: "to_date", fieldtype: "Date", label: __("To Date"), change: () => this.refresh() });
		page.set_primary_action(__("Pay Supplier"), () => this.pay(), "money-coins-1");
		page.add_inner_button(__("Record Invoice"), () => this.new_invoice());
		this.$main = $('<div class="sp-ledger"></div>').appendTo(page.main);
	}

	show() {
		const options = frappe.route_options;
		frappe.route_options = null;
		if (options?.supplier) {
			this.supplier.set_value(options.supplier);
		} else {
			this.refresh();
		}
	}

	money(value) {
		return format_currency(value, this.currency);
	}

	async refresh() {
		const supplier = this.supplier.get_value();
		this.$main.empty();
		if (!supplier) {
			$(`<p class="text-muted mt-3">${frappe.utils.escape_html(__("Choose a supplier to see their ledger."))}</p>`).appendTo(this.$main);
			return;
		}
		const { message: data } = await frappe.call(`${SP_SL_API}.supplier_ledger`, {
			supplier,
			from_date: this.from_date.get_value() || null,
			to_date: this.to_date.get_value() || null,
		});
		this.currency = data.currency;
		this.$main.empty();
		this.render_summary(data);
		this.render_stations(data);
		this.render_open(data);
		this.render_rows(data);
	}

	render_summary(data) {
		const esc = frappe.utils.escape_html;
		const tile = (label, value, cls) => `<div class="frappe-card p-3 sp-ledger-tile" style="flex: 1 1 220px">
			<div class="small text-muted">${esc(label)}</div><div class="h4 mb-0 ${cls || ""}">${esc(this.money(value))}</div></div>`;
		$(`<div class="d-flex flex-wrap my-3" style="gap: 12px">
			${tile(__("Balance Owed"), data.balance)}
			${tile(__("Due This Week"), data.due_this_week, data.due_this_week ? "text-danger" : "")}
		</div>`).appendTo(this.$main);
	}

	section(title, head, rows, empty, numbers = 1) {
		const esc = frappe.utils.escape_html;
		const first_number = head.length - numbers;
		const heads = head.map((h, i) => `<th${i >= first_number ? ' class="text-right"' : ""}>${esc(h)}</th>`).join("");
		const body = rows.length
			? `<div class="table-responsive"><table class="table table-sm mb-0"><thead><tr>${heads}</tr></thead>
				<tbody>${rows.join("")}</tbody></table></div>`
			: `<p class="text-muted mb-0">${esc(empty)}</p>`;
		$(`<div class="frappe-card p-3 mb-3"><h6 class="mb-2">${esc(title)}</h6>${body}</div>`).appendTo(this.$main);
	}

	link(doctype, name) {
		const esc = frappe.utils.escape_html;
		return `<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}">${esc(name)}</a>`;
	}

	render_stations(data) {
		const esc = frappe.utils.escape_html;
		const rows = data.stations.map((r) => `<tr class="sp-ledger-station"><td>${esc(r.station || __("No station"))}</td><td class="text-right">${esc(this.money(r.amount))}</td></tr>`);
		this.section(__("Owed by Station"), [__("Station"), __("Amount")], rows, __("Nothing is owed to this supplier."));
	}

	render_open(data) {
		const esc = frappe.utils.escape_html;
		const rows = data.open_invoices.map((r) => {
			const color = r.overdue ? "red" : r.due_this_week ? "orange" : "gray";
			const label = r.overdue ? __("Overdue") : r.due_this_week ? __("Due this week") : __("Open");
			return `<tr class="sp-ledger-open">
				<td>${this.link("Purchase Invoice", r.name)}<div class="small text-muted">${esc(r.bill_no || "")}</div></td>
				<td class="text-nowrap">${esc(frappe.datetime.str_to_user(r.due_date))}</td>
				<td><span class="indicator-pill ${color}">${esc(label)}</span></td>
				<td class="text-right">${esc(this.money(r.grand_total))}</td>
				<td class="text-right">${esc(this.money(r.outstanding_amount))}</td>
			</tr>`;
		});
		this.section(__("Open Invoices"), [__("Invoice"), __("Due Date"), __("Status"), __("Total"), __("Outstanding")], rows, __("No open invoices."), 2); // sp-allow-number: two money columns
	}

	render_rows(data) {
		const esc = frappe.utils.escape_html;
		const rows = data.rows.map(
			(r) => `<tr class="sp-ledger-row">
				<td class="text-nowrap">${esc(frappe.datetime.str_to_user(r.date))}</td>
				<td>${esc(__(r.kind))}</td>
				<td>${this.link(r.voucher_type, r.voucher_no)}${r.against ? `<div class="small text-muted">${esc(r.against)}</div>` : ""}</td>
				<td class="text-right">${r.credit ? esc(this.money(r.credit)) : ""}</td>
				<td class="text-right">${r.debit ? esc(this.money(r.debit)) : ""}</td>
				<td class="text-right"><b>${esc(this.money(r.balance))}</b></td>
			</tr>`
		);
		if (data.opening) {
			rows.unshift(`<tr><td colspan="5">${esc(__("Balance brought forward"))}</td><td class="text-right"><b>${esc(this.money(data.opening))}</b></td></tr>`);
		}
		this.section(__("Ledger"), [__("Date"), __("Type"), __("Document"), __("Billed"), __("Paid"), __("Balance")], rows, __("No entries in this period."), 3); // sp-allow-number: three money columns
	}

	new_invoice() {
		frappe.new_doc("Purchase Invoice", { supplier: this.supplier.get_value() || undefined });
	}

	async pay() {
		const supplier = this.supplier.get_value();
		if (!supplier) {
			frappe.msgprint(__("Choose a supplier first."));
			return;
		}
		const { message: options } = await frappe.call(`${SP_SP_API}.payment_options`, { supplier });
		let photo = null;
		const dialog = new frappe.ui.Dialog({
			title: __("Pay {0}", [supplier]),
			fields: [
				{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), reqd: 1 },
				{ fieldname: "account", fieldtype: "Select", label: __("Pay From"), options: options.accounts, reqd: 1 },
				{ fieldname: "posting_date", fieldtype: "Date", label: __("Date"), default: frappe.datetime.get_today(), reqd: 1 },
				{ fieldname: "reference_no", fieldtype: "Data", label: __("Payment Reference"), reqd: 1 },
				{
					fieldname: "purchase_order",
					fieldtype: "Select",
					label: __("Purchase Order"),
					options: ["", ...options.orders.map((o) => o.name)],
					description: __("Leave empty to pay the earliest due invoices."),
				},
				{ fieldname: "receipt", fieldtype: "Button", label: __("Attach Receipt") },
				{ fieldname: "receipt_name", fieldtype: "HTML" },
			],
			primary_action_label: __("Send for Confirmation"),
			primary_action: async (values) => {
				if (!photo) {
					frappe.msgprint(__("Attach the payment receipt."));
					return;
				}
				const { receipt, receipt_name, ...rest } = values;
				await frappe.call({
					method: `${SP_SP_API}.record_payment`,
					args: { values: { ...rest, supplier, company: options.company, receipt_photo: photo } },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Payment sent to the admin for confirmation"), indicator: "green" });
				this.refresh();
			},
		});
		dialog.fields_dict.receipt.input.onclick = () => {
			new frappe.ui.FileUploader({
				allow_multiple: false,
				restrictions: { allowed_file_types: ["image/*", "application/pdf"] },
				make_attachments_public: false,
				on_success: (file) => {
					photo = file.file_url;
					dialog.fields_dict.receipt_name.$wrapper.html(`<p class="small text-success">${frappe.utils.escape_html(file.file_name)}</p>`);
				},
			});
		};
		dialog.show();
	}
}
