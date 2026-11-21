// SH1 Showroom sale (SP-102): the cashier finds the items, sells them from the showroom store at
// the customer's prices, takes the money and prints the receipt; an earlier receipt can be
// returned. Cash goes into the showroom box. The rules are on the server
// (smart_power.sp_sales.showroom_sale).

const SP_SH1_API = "smart_power.sp_sales.showroom_sale";
const SP_SH1_MIN_SEARCH = 2; // sp-allow-number: as the server, two letters before searching
const SP_SH1_MONEY_DIGITS = 2; // sp-allow-number: piastres

frappe.pages["sp-showroom-sale"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Showroom Sale"),
		single_column: true,
	});
	wrapper.sp_showroom_sale = new SPShowroomSale(page);
};

frappe.pages["sp-showroom-sale"].on_page_show = function (wrapper) {
	wrapper.sp_showroom_sale && wrapper.sp_showroom_sale.load_today();
};

function sp_print_html(html) {
	const win = window.open("", "_blank");
	if (!win) {
		frappe.msgprint(__("Allow pop-ups to print the receipt."));
		return;
	}
	win.document.write(html);
	win.document.close();
	win.focus();
	setTimeout(() => win.print(), 500); // sp-allow-number: let the receipt's font load first
}

class SPShowroomSale {
	constructor(page) {
		this.page = page;
		this.cart = [];
		this.customer = null; // null: the walk-in customer
		this.page.set_primary_action(__("Sell and Print"), () => this.sell(), "printer");
		this.page.set_secondary_action(__("Return a Receipt"), () => this.start_return());
		this.$main = $(`<div class="sp-sh1 row">
			<div class="col-md-7">
				<div class="sp-sh1-customer border rounded p-3 mb-3"></div>
				<div class="sp-sh1-search"></div>
				<div class="sp-sh1-results mb-3"></div>
			</div>
			<div class="col-md-5">
				<div class="sp-sh1-cart border rounded p-3 mb-3"></div>
			</div>
			<div class="col-12 sp-sh1-today"></div>
		</div>`).appendTo(this.page.main);
		this.ready = frappe.call(`${SP_SH1_API}.options`).then(({ message }) => {
			this.options = message;
			this.mode = (message.modes[0] || {}).mode;
			this.render_customer();
			this.render_cart();
		});
		this.make_search();
		this.load_today();
	}

	make_search() {
		this.search = frappe.ui.form.make_control({
			parent: this.$main.find(".sp-sh1-search"),
			df: {
				fieldname: "q",
				fieldtype: "Data",
				label: __("Search items"),
				placeholder: __("Name, code or brand"),
				change: () => this.find_items(),
			},
			render_input: true,
		});
		this.search.$input.on(
			"input",
			frappe.utils.debounce(() => this.find_items(), 400) // sp-allow-number: ms between keys
		);
	}

	render_customer() {
		const esc = frappe.utils.escape_html;
		const o = this.options;
		const c = this.customer || o.walk_in;
		const $box = this.$main.find(".sp-sh1-customer").empty();
		$box.append(`<div class="d-flex justify-content-between align-items-center flex-wrap">
			<div><div class="text-muted small">${esc(__("Customer"))}</div>
				<h5 class="mb-0">${esc(c.customer_name)}</h5>
				<div class="small text-muted">${esc(__("Prices: {0}", [c.price_list]))}</div></div>
			<div class="sp-sh1-mobile" style="min-width: 220px"></div>
		</div>`);
		const mobile = frappe.ui.form.make_control({
			parent: $box.find(".sp-sh1-mobile"),
			df: {
				fieldname: "mobile",
				fieldtype: "Data",
				label: __("Customer mobile"),
				placeholder: "01xxxxxxxxx",
				change: () => this.find_customer(mobile.get_value()),
			},
			render_input: true,
		});
		if (this.customer) {
			$(`<button class="btn btn-xs btn-default mt-1"></button>`)
				.text(__("Walk-in customer"))
				.on("click", () => this.set_customer(null))
				.appendTo($box.find(".sp-sh1-mobile"));
		}
	}

	async find_customer(mobile) {
		mobile = (mobile || "").trim();
		if (!mobile) return;
		const { message } = await frappe.call(`${SP_SH1_API}.find_customer`, { mobile });
		if (!message) {
			frappe.show_alert({
				message: __("No customer has this mobile; the sale stays on the walk-in customer."),
				indicator: "orange",
			});
			return;
		}
		this.set_customer(message);
	}

	set_customer(customer) {
		const changed = (this.customer || {}).name !== (customer || {}).name;
		this.customer = customer;
		this.render_customer();
		if (changed && this.cart.length) {
			this.cart = [];
			frappe.show_alert({ message: __("Prices changed: add the items again."), indicator: "blue" });
		}
		this.render_cart();
		this.find_items();
	}

	async find_items() {
		const esc = frappe.utils.escape_html;
		const q = (this.search.get_value() || "").trim();
		const ticket = (this.ticket = (this.ticket || 0) + 1);
		const $results = this.$main.find(".sp-sh1-results");
		if (q.length < SP_SH1_MIN_SEARCH) {
			$results.empty();
			return;
		}
		const { message: rows } = await frappe.call(`${SP_SH1_API}.find_items`, {
			q,
			customer: (this.customer || {}).name,
		});
		if (ticket !== this.ticket) return;
		$results.empty();
		if (!rows.length) {
			$results.html(`<div class="text-muted p-2">${esc(__("No item found."))}</div>`);
			return;
		}
		const $table = $(`<table class="table table-sm table-hover"><thead><tr>
			<th>${esc(__("Item"))}</th><th class="text-right">${esc(__("In the showroom"))}</th>
			<th class="text-right">${esc(__("Price"))}</th><th></th></tr></thead><tbody></tbody></table>`).appendTo(
			$results
		);
		rows.forEach((r) => {
			const $tr = $(`<tr>
				<td>${esc(r.item_name)}<div class="small text-muted">${esc(r.item_code)}</div></td>
				<td class="text-right">${esc(format_number(r.in_stock))}</td>
				<td class="text-right">${r.price ? esc(format_currency(r.price)) : esc(__("No price"))}</td>
				<td></td></tr>`).appendTo($table.find("tbody"));
			if (r.price && r.in_stock > 0) {
				$(`<button class="btn btn-xs btn-primary"></button>`)
					.text(__("Add"))
					.on("click", () => this.add(r))
					.appendTo($tr.find("td:last"));
			}
		});
	}

	add(row) {
		const line = this.cart.find((l) => l.item_code === row.item_code);
		if (line) {
			line.qty = Math.min(line.qty + 1, row.in_stock);
		} else {
			this.cart.push({ ...row, qty: 1, discount_pct: 0 });
		}
		this.render_cart();
	}

	line_amount(l) {
		return flt(l.price * (1 - flt(l.discount_pct) / 100) * flt(l.qty), SP_SH1_MONEY_DIGITS); // sp-allow-number: percent
	}

	totals() {
		const listed = this.cart.reduce((s, l) => s + flt(l.price) * flt(l.qty), 0);
		const lines = this.cart.reduce((s, l) => s + this.line_amount(l), 0);
		const total = flt(lines - flt(this.discount_amount), SP_SH1_MONEY_DIGITS);
		return { listed, lines, total, discount: flt(listed - total, SP_SH1_MONEY_DIGITS) };
	}

	render_cart() {
		if (!this.options) return;
		const esc = frappe.utils.escape_html;
		const $cart = this.$main.find(".sp-sh1-cart").empty();
		$cart.append(`<h5>${esc(__("The sale"))}</h5>`);
		if (!this.cart.length) {
			this.discount_amount = 0;
			$cart.append(`<div class="text-muted">${esc(__("Search for an item and add it."))}</div>`);
			return;
		}
		const $table = $(`<table class="table table-sm"><thead><tr>
			<th>${esc(__("Item"))}</th><th>${esc(__("Qty"))}</th><th>${esc(__("Discount %"))}</th>
			<th class="text-right">${esc(__("Amount"))}</th><th></th></tr></thead><tbody></tbody></table>`).appendTo(
			$cart
		);
		this.cart.forEach((l, i) => {
			const $tr = $(`<tr>
				<td>${esc(l.item_name)}<div class="small text-muted">${esc(format_currency(l.price))}</div></td>
				<td><input type="number" min="1" max="${l.in_stock}" step="1" class="form-control input-xs sp-qty" style="width: 70px"></td>
				<td><input type="number" min="0" max="99" step="0.5" class="form-control input-xs sp-disc" style="width: 70px"></td>
				<td class="text-right">${esc(format_currency(this.line_amount(l)))}</td>
				<td><button class="btn btn-xs btn-default sp-remove">×</button></td></tr>`).appendTo(
				$table.find("tbody")
			);
			$tr.find(".sp-qty")
				.val(l.qty)
				.on("change", (e) => {
					l.qty = Math.max(Math.min(flt(e.target.value), l.in_stock), 1);
					this.render_cart();
				});
			$tr.find(".sp-disc")
				.val(l.discount_pct)
				.on("change", (e) => {
					l.discount_pct = Math.max(Math.min(flt(e.target.value), 99), 0); // sp-allow-number: under 100%
					this.render_cart();
				});
			$tr.find(".sp-remove").on("click", () => {
				this.cart.splice(i, 1);
				this.render_cart();
			});
		});
		const t = this.totals();
		const $foot = $(`<div>
			<div class="d-flex justify-content-between"><span>${esc(__("Before discount"))}</span>
				<span>${esc(format_currency(t.listed))}</span></div>
			<div class="d-flex justify-content-between align-items-center my-1"><span>${esc(
				__("Discount on the total")
			)}</span>
				<input type="number" min="0" step="1" class="form-control input-xs sp-total-disc" style="width: 110px"></div>
			<div class="d-flex justify-content-between"><span>${esc(__("Discount to the customer"))}</span>
				<span>${esc(format_currency(t.discount))}</span></div>
			<div class="d-flex justify-content-between mt-2"><strong>${esc(__("Total"))}</strong>
				<h4 class="mb-0">${esc(format_currency(t.total))}</h4></div>
			<div class="mt-3 sp-sh1-mode"></div>
			<div class="small text-muted sp-sh1-mode-note"></div>
		</div>`).appendTo($cart);
		$foot
			.find(".sp-total-disc")
			.val(this.discount_amount || 0)
			.on("change", (e) => {
				this.discount_amount = Math.max(flt(e.target.value), 0);
				this.render_cart();
			});
		const $mode = $(`<select class="form-control"></select>`).appendTo($foot.find(".sp-sh1-mode"));
		this.options.modes.forEach((m) => $mode.append(new Option(m.label, m.mode)));
		$mode.val(this.mode).on("change", () => {
			this.mode = $mode.val();
			this.render_cart();
		});
		const mode = this.options.modes.find((m) => m.mode === this.mode) || {};
		$foot
			.find(".sp-sh1-mode-note")
			.text(
				mode.is_cash
					? __("Cash goes into the showroom box.")
					: __("Paid to {0}.", [mode.account || ""])
			);
		if (!mode.is_cash) {
			this.reference = frappe.ui.form.make_control({
				parent: $foot,
				df: { fieldname: "reference_no", fieldtype: "Data", label: __("Reference") },
				render_input: true,
			});
		} else {
			this.reference = null;
		}
	}

	async sell() {
		await this.ready;
		if (!this.cart.length) {
			frappe.msgprint(__("Add at least one item."));
			return;
		}
		const t = this.totals();
		frappe.confirm(
			__("Sell for {0} to {1}?", [
				format_currency(t.total),
				(this.customer || this.options.walk_in).customer_name,
			]),
			async () => {
				const { message } = await frappe.call({
					method: `${SP_SH1_API}.sell`,
					args: {
						values: {
							customer: (this.customer || {}).name,
							items: this.cart.map((l) => ({
								item_code: l.item_code,
								qty: l.qty,
								discount_pct: l.discount_pct,
							})),
							discount_amount: this.discount_amount || 0,
							mode_of_payment: this.mode,
							reference_no: this.reference ? this.reference.get_value() : null,
						},
					},
					freeze: true,
				});
				frappe.show_alert({ message: __("{0} is posted.", [message.name]), indicator: "green" });
				this.cart = [];
				this.discount_amount = 0;
				this.set_customer(null);
				this.print(message.name);
				this.load_today();
			}
		);
	}

	async print(name) {
		const { message: html } = await frappe.call(`${SP_SH1_API}.receipt`, { name });
		sp_print_html(html);
	}

	start_return() {
		const dialog = new frappe.ui.Dialog({
			title: __("Return a Receipt"),
			fields: [
				{ fieldname: "receipt", fieldtype: "Data", label: __("Receipt No."), reqd: 1 },
				{ fieldname: "lines", fieldtype: "HTML" },
			],
			primary_action_label: __("Find"),
			primary_action: async ({ receipt }) => {
				if (dialog.sp_receipt) return this.do_return(dialog);
				const { message } = await frappe.call(`${SP_SH1_API}.find_receipt`, { name: receipt });
				dialog.sp_receipt = message;
				this.render_return(dialog);
				dialog.set_primary_action(__("Return and Print"), () => this.do_return(dialog));
			},
		});
		dialog.show();
	}

	render_return(dialog) {
		const esc = frappe.utils.escape_html;
		const r = dialog.sp_receipt;
		const rows = r.items
			.map(
				(l, i) => `<tr><td>${esc(l.item_name)}</td>
				<td class="text-right">${esc(format_number(l.qty))}</td>
				<td class="text-right">${esc(format_currency(l.rate))}</td>
				<td><input type="number" min="0" max="${l.returnable}" step="1" value="0" data-i="${i}"
					class="form-control input-xs sp-ret" style="width: 70px" ${l.returnable ? "" : "disabled"}></td></tr>`
			)
			.join("");
		dialog.fields_dict.lines.$wrapper.html(`<div class="mb-2">${esc(r.customer_name)} ·
			${esc(frappe.datetime.str_to_user(r.posting_date))} · ${esc(format_currency(r.grand_total))}</div>
			<table class="table table-sm"><thead><tr><th>${esc(__("Item"))}</th>
			<th class="text-right">${esc(__("Sold"))}</th><th class="text-right">${esc(__("Price"))}</th>
			<th>${esc(__("Return"))}</th></tr></thead><tbody>${rows}</tbody></table>
			<div class="small text-muted">${esc(__("The money goes back out of the showroom box in cash."))}</div>`);
	}

	async do_return(dialog) {
		const r = dialog.sp_receipt;
		const items = [];
		dialog.fields_dict.lines.$wrapper.find(".sp-ret").each((_i, el) => {
			const qty = Math.min(flt(el.value), r.items[el.dataset.i].returnable);
			if (qty > 0) items.push({ item_code: r.items[el.dataset.i].item_code, qty });
		});
		if (!items.length) {
			frappe.msgprint(__("Choose the items to return and their quantity."));
			return;
		}
		const { message } = await frappe.call({
			method: `${SP_SH1_API}.return_sale`,
			args: { invoice: r.name, items },
			freeze: true,
		});
		dialog.hide();
		frappe.show_alert({
			message: __("{0}: {1} refunded from the box.", [message.name, format_currency(message.refund)]),
			indicator: "green",
		});
		this.print(message.name);
		this.load_today();
	}

	async load_today() {
		const esc = frappe.utils.escape_html;
		const { message: rows } = await frappe.call(`${SP_SH1_API}.today_sales`);
		const $today = this.$main.find(".sp-sh1-today").empty();
		$today.append(`<h5>${esc(__("Showroom receipts today"))}</h5>`);
		if (!rows.length) {
			$today.append(`<div class="text-muted">${esc(__("Nothing yet today."))}</div>`);
			return;
		}
		const $table = $(`<table class="table table-sm"><thead><tr>
			<th>${esc(__("Receipt No."))}</th><th>${esc(__("Customer"))}</th>
			<th class="text-right">${esc(__("Total"))}</th><th></th><th></th></tr></thead><tbody></tbody></table>`).appendTo(
			$today
		);
		rows.forEach((r) => {
			const $tr = $(`<tr><td>${esc(r.name)}</td><td>${esc(r.customer_name || "")}</td>
				<td class="text-right">${esc(format_currency(r.grand_total))}</td>
				<td>${
					r.is_return
						? `<span class="indicator-pill red">${esc(__("Return of {0}", [r.return_against]))}</span>`
						: ""
				}</td><td></td></tr>`).appendTo($table.find("tbody"));
			$(`<button class="btn btn-xs btn-default"></button>`)
				.text(__("Print"))
				.on("click", () => this.print(r.name))
				.appendTo($tr.find("td:last"));
		});
	}
}
