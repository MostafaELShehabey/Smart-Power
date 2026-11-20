// SH5 Payment on a station at the showroom (SP-103): find the station by the customer's name,
// mobile or the station number, see what is still owed and the schedule, and take the payment.
// It is credited to the station, pending the admin's confirmation; cash goes into the showroom
// box. The rules are on the server (smart_power.sp_finance.showroom_payment).

const SP_SH5_API = "smart_power.sp_finance.showroom_payment";

frappe.pages["sp-showroom-payment"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Station Payment at the Showroom"),
		single_column: true,
	});
	wrapper.sp_showroom_payment = new SPShowroomPayment(page);
};

frappe.pages["sp-showroom-payment"].on_page_show = function (wrapper) {
	wrapper.sp_showroom_payment && wrapper.sp_showroom_payment.load_today();
};

class SPShowroomPayment {
	constructor(page) {
		this.page = page;
		this.search = this.page.add_field({
			fieldname: "q",
			fieldtype: "Data",
			label: __("Customer name, mobile or station"),
			change: () => this.find(),
		});
		this.$results = $('<div class="sp-sh5-results mb-4"></div>').appendTo(this.page.main);
		this.$today = $('<div class="sp-sh5-today"></div>').appendTo(this.page.main);
		this.ready = frappe.call(`${SP_SH5_API}.options`).then(({ message }) => (this.options = message));
		this.load_today();
	}

	async find() {
		const esc = frappe.utils.escape_html;
		const q = (this.search.get_value() || "").trim();
		// only the latest search draws: an Enter and a blur can send the same search twice
		const ticket = (this.ticket = (this.ticket || 0) + 1);
		this.$results.empty();
		if (q.length < 3) return; // sp-allow-number: as the server, three letters before searching
		const { message: rows } = await frappe.call(`${SP_SH5_API}.find_station`, { q });
		if (ticket !== this.ticket) return;
		this.$results.empty();
		if (!rows.length) {
			this.$results.html(`<div class="text-muted p-3">${esc(__("No open station found."))}</div>`);
			return;
		}
		rows.forEach((row) => this.render_station(row));
	}

	render_station(row) {
		const esc = frappe.utils.escape_html;
		const next = row.next_due
			? __("Next: {0} on {1}", [
					format_currency(row.next_due.left),
					frappe.datetime.str_to_user(row.next_due.due_date),
			  ])
			: __("Nothing left on the schedule");
		const schedule = row.schedule
			.map((r) => {
				const colour = { Paid: "green", Overdue: "red" }[r.status] || "blue";
				return `<tr><td>${esc(frappe.datetime.str_to_user(r.due_date))}</td>
					<td class="text-right">${esc(format_currency(r.amount))}</td>
					<td class="text-right">${esc(format_currency(r.left))}</td>
					<td><span class="indicator-pill ${colour}">${esc(__(r.status))}</span></td></tr>`;
			})
			.join("");
		const $card = $(`<div class="sp-sh5-station border rounded p-3 mb-3">
			<div class="d-flex justify-content-between flex-wrap">
				<div><h5 class="mb-1">${esc(row.customer_name || row.customer)}</h5>
					<div class="text-muted">${esc(row.station)} · ${esc(__(row.status))}</div></div>
				<div class="text-right"><div class="text-muted small">${esc(__("Remaining"))}</div>
					<h4 class="mb-0">${esc(format_currency(row.remaining))}</h4>
					${
						row.pending
							? `<div class="small text-warning">${esc(
									__("{0} waiting for the admin", [format_currency(row.pending)])
							  )}</div>`
							: ""
					}</div>
			</div>
			<div class="mt-2">${esc(next)}</div>
			<table class="table table-sm mt-2 mb-2"><thead><tr><th>${esc(__("Due Date"))}</th>
				<th class="text-right">${esc(__("Amount"))}</th><th class="text-right">${esc(
			__("Left")
		)}</th><th></th></tr></thead><tbody>${schedule}</tbody></table>
		</div>`).appendTo(this.$results);
		$(`<button class="btn btn-primary btn-sm"></button>`)
			.text(__("Take a Payment"))
			.on("click", () => this.take(row))
			.appendTo($card);
	}

	async take(row) {
		await this.ready;
		const o = this.options;
		const dialog = new frappe.ui.Dialog({
			title: __("Payment on {0}", [row.station]),
			fields: [
				{
					fieldname: "amount",
					fieldtype: "Currency",
					label: __("Amount"),
					reqd: 1,
					default: row.next_due ? row.next_due.left : row.remaining,
				},
				{
					fieldname: "method",
					fieldtype: "Select",
					label: __("Method"),
					reqd: 1,
					options: o.methods.map((m) => ({ value: m.name, label: m.label })),
					default: o.cash,
				},
				{
					fieldname: "receiving_account",
					fieldtype: "Select",
					label: __("To Account"),
					options: o.accounts,
					depends_on: `eval:doc.method !== "${o.cash}"`,
					mandatory_depends_on: `eval:doc.method !== "${o.cash}"`,
				},
				{
					fieldname: "reference_no",
					fieldtype: "Data",
					label: __("Reference"),
					depends_on: `eval:doc.method !== "${o.cash}"`,
				},
				{
					fieldname: "receipt_photo",
					fieldtype: "Attach Image",
					label: __("Receipt Photo"),
					depends_on: `eval:doc.method !== "${o.cash}"`,
					mandatory_depends_on: `eval:doc.method !== "${o.cash}"`,
				},
				{
					fieldname: "box_note",
					fieldtype: "HTML",
					depends_on: `eval:doc.method === "${o.cash}"`,
					options: `<div class="text-muted small">${frappe.utils.escape_html(
						__("Cash goes into the showroom box until it is deposited.")
					)}</div>`,
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				delete values.box_note;
				const { message: name } = await frappe.call({
					method: `${SP_SH5_API}.record`,
					args: { values: { ...values, station: row.station } },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({
					message: __("{0} is waiting for the admin's confirmation.", [name]),
					indicator: "green",
				});
				this.find();
				this.load_today();
			},
		});
		dialog.show();
	}

	async load_today() {
		const esc = frappe.utils.escape_html;
		const { message: rows } = await frappe.call(`${SP_SH5_API}.today`);
		this.$today.empty();
		this.$today.append(`<h5>${esc(__("Taken at the showroom today"))}</h5>`);
		if (!rows.length) {
			this.$today.append(`<div class="text-muted">${esc(__("Nothing yet today."))}</div>`);
			return;
		}
		const colour = { Pending: "orange", Confirmed: "green", Rejected: "red" };
		const $table = $(`<table class="table table-sm"><thead><tr>
			<th>${esc(__("Payment"))}</th><th>${esc(__("Station"))}</th><th>${esc(__("Customer"))}</th>
			<th class="text-right">${esc(__("Amount"))}</th><th>${esc(__("Status"))}</th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$today);
		rows.forEach((r) =>
			$table.find("tbody").append(`<tr>
				<td><a href="/app/sp-customer-payment/${encodeURIComponent(r.name)}">${esc(r.name)}</a></td>
				<td>${esc(r.station || "")}</td><td>${esc(r.customer_name || "")}</td>
				<td class="text-right">${esc(format_currency(r.amount))}</td>
				<td><span class="indicator-pill ${colour[r.status] || "blue"}">${esc(__(r.status))}</span></td>
			</tr>`)
		);
	}
}
