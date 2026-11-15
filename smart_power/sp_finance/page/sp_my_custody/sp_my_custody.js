// A9 My custody (SP-122): my custody balance, each expense with where it lands and its status,
// Add Expense (date, amount, type, station / center / petty cash, receipt photo, note) and Submit
// Settlement (carry the leftover or return it). Rejected expenses show the admin's reason and can be
// settled again. The admin and the accountant may open a holder's view. The rules are on the
// server (smart_power.sp_finance.custody).

const SP_MC_API = "smart_power.sp_finance.custody";
const SP_MC_STATUS = { Draft: "gray", "In settlement": "purple", Approved: "green", Rejected: "red" };

frappe.pages["sp-my-custody"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("My Custody"), single_column: true });
	wrapper.sp_my_custody = new SPMyCustody(page);
};

frappe.pages["sp-my-custody"].on_page_show = function (wrapper) {
	const holder = frappe.route_options && frappe.route_options.holder;
	frappe.route_options = null;
	if (wrapper.sp_my_custody) {
		if (holder) wrapper.sp_my_custody.holder = holder;
		wrapper.sp_my_custody.refresh();
	}
};

class SPMyCustody {
	constructor(page) {
		this.page = page;
		this.holder = null;
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.$body = $('<div class="sp-mc-body"></div>').appendTo(this.page.main);
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_MC_API}.my_custody`, { holder: this.holder });
		this.data = message;
		this.holder_filter();
		this.render();
	}

	holder_filter() {
		if (!this.data.is_admin || this.holder_field) return;
		this.holder_field = this.page.add_field({
			fieldname: "holder",
			fieldtype: "Link",
			options: "User",
			label: __("Holder"),
			default: this.data.holder,
			change: () => {
				const value = this.holder_field.get_value();
				if (value && value !== this.holder) {
					this.holder = value;
					this.refresh();
				}
			},
		});
	}

	render() {
		const esc = frappe.utils.escape_html;
		const money = (v) => esc(format_currency(v || 0));
		const date = (d) => (d ? esc(frappe.datetime.str_to_user(d)) : "");
		this.$body.empty();
		$(`<div class="sp-mc-balance mb-4 px-3">
			<div class="text-muted small">${esc(__("Custody balance"))}</div>
			<div class="sp-mc-amount">${money(this.data.balance)}</div>
		</div>`).appendTo(this.$body);
		if (!this.data.custodies.length) {
			$(`<div class="text-muted text-center p-5">${esc(__("No open custody."))}</div>`).appendTo(this.$body);
		}
		const mine = this.data.holder === frappe.session.user;
		this.data.custodies.forEach((c) => {
			const open = c.lines.filter((r) => ["Draft", "Rejected"].includes(r.status));
			const $card = $(`<div class="sp-mc-card">
				<div class="sp-mc-head">
					<div><a href="/app/sp-custody/${encodeURIComponent(c.name)}"><b>${esc(c.name)}</b></a>
						<span class="text-muted small">${esc(__("Given {0} on {1}", [format_currency(c.amount), frappe.datetime.str_to_user(c.given_on)]))}</span>
						<span class="indicator-pill gray ml-2">${esc(__(c.status))}</span></div>
					<div class="sp-mc-actions"></div>
				</div>
				<table class="table table-sm mt-2"><thead><tr>
					<th>${esc(__("Date"))}</th><th>${esc(__("Expense Type"))}</th><th>${esc(__("Charged To"))}</th>
					<th class="text-right">${esc(__("Amount"))}</th><th>${esc(__("Status"))}</th><th></th>
				</tr></thead><tbody></tbody></table>
			</div>`).appendTo(this.$body);
			const $tbody = $card.find("tbody");
			if (!c.lines.length) {
				$tbody.append(`<tr><td colspan="6" class="text-muted">${esc(__("No expenses yet."))}</td></tr>`);
			}
			c.lines.forEach((r) => {
				const $tr = $(`<tr>
					<td>${date(r.work_date)}</td><td>${esc(r.type_label)}</td><td>${esc(r.where)}</td>
					<td class="text-right">${money(r.amount)}</td>
					<td><span class="indicator-pill ${SP_MC_STATUS[r.status] || "gray"}">${esc(__(r.status))}</span>
						${r.reject_reason ? `<div class="small text-danger">${esc(r.reject_reason)}</div>` : ""}</td>
					<td class="text-nowrap"></td>
				</tr>`).appendTo($tbody);
				if (r.receipt_photo) {
					$(`<a class="btn btn-xs btn-default mr-1" target="_blank"></a>`)
						.attr("href", r.receipt_photo)
						.text(__("Receipt"))
						.appendTo($tr.find("td:last"));
				}
				if (["Draft", "Rejected"].includes(r.status)) {
					$(`<button class="btn btn-xs btn-default"></button>`)
						.text(__("Remove"))
						.on("click", () =>
							frappe.confirm(__("Remove this expense?"), async () => {
								await frappe.call(`${SP_MC_API}.remove_expense`, { custody: c.name, line: r.name });
								this.refresh();
							})
						)
						.appendTo($tr.find("td:last"));
				}
			});
			if (!mine && !this.data.is_admin) return;
			const $act = $card.find(".sp-mc-actions");
			$(`<button class="btn btn-xs btn-default mr-1"></button>`)
				.text(__("Add Expense"))
				.on("click", () => this.add_expense(c))
				.appendTo($act);
			if (open.length) {
				$(`<button class="btn btn-xs btn-primary"></button>`)
					.text(__("Submit Settlement"))
					.on("click", () => this.settle(c, open))
					.appendTo($act);
			}
		});
		if (this.data.settlements.length) {
			const $s = $(`<div class="mt-4 px-3"><h6>${esc(__("Settlements"))}</h6></div>`).appendTo(this.$body);
			this.data.settlements.forEach((s) =>
				$s.append(`<div class="small"><a href="/app/sp-custody-settlement/${encodeURIComponent(s.name)}">${esc(s.name)}</a>
					· ${money(s.total)} · ${esc(__(s.status))} · ${esc(__(s.leftover_action))}</div>`)
			);
		}
	}

	add_expense(c) {
		const d = new frappe.ui.Dialog({
			title: __("Add Expense"),
			fields: [
				{ fieldname: "work_date", fieldtype: "Date", label: __("Date"), default: "Today", reqd: 1 },
				{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), reqd: 1 },
				{
					fieldname: "expense_type",
					fieldtype: "Link",
					options: "SP List Value",
					label: __("Expense Type"),
					reqd: 1,
					get_query: () => ({ filters: { list_name: "Expense Type", is_active: 1 } }),
				},
				{
					fieldname: "center_type",
					fieldtype: "Select",
					label: __("Charged To"),
					options: [
						{ value: "Station", label: __("Station") },
						{ value: "Center", label: __("Center") },
						{ value: "Petty cash", label: __("Petty cash") },
					],
					default: "Station",
					reqd: 1,
				},
				{
					fieldname: "station",
					fieldtype: "Autocomplete",
					label: __("Station"),
					options: this.data.stations.filter((r) => r.company === c.company),
					depends_on: "eval:doc.center_type==='Station'",
					mandatory_depends_on: "eval:doc.center_type==='Station'",
				},
				{
					fieldname: "cost_center",
					fieldtype: "Autocomplete",
					label: __("Center"),
					options: this.data.centers.filter((r) => r.company === c.company),
					depends_on: "eval:doc.center_type!=='Station'",
					mandatory_depends_on: "eval:doc.center_type!=='Station'",
				},
				{ fieldname: "receipt_photo", fieldtype: "Attach Image", label: __("Receipt Photo") },
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await frappe.call({
					method: `${SP_MC_API}.add_expense`,
					args: { custody: c.name, values },
					freeze: true,
				});
				d.hide();
				this.refresh();
			},
		});
		d.show();
	}

	settle(c, open) {
		const total = open.reduce((sum, r) => sum + r.amount, 0);
		const d = new frappe.ui.Dialog({
			title: __("Submit Settlement"),
			fields: [
				{
					fieldname: "summary",
					fieldtype: "HTML",
					options: `<p>${frappe.utils.escape_html(
						__("{0} expenses, {1}. The admin approves them in Confirmations.", [open.length, format_currency(total)])
					)}</p>`,
				},
				{
					fieldname: "leftover_action",
					fieldtype: "Select",
					label: __("Leftover Cash"),
					options: [
						{ value: "Carry", label: __("Carry to the next period") },
						{ value: "Return", label: __("Return to an official account") },
					],
					default: "Carry",
					reqd: 1,
				},
				{
					fieldname: "return_to_account",
					fieldtype: "Autocomplete",
					label: __("Return To"),
					options: this.data.return_accounts.filter((r) => r.company === c.company),
					depends_on: "eval:doc.leftover_action==='Return'",
					mandatory_depends_on: "eval:doc.leftover_action==='Return'",
				},
			],
			primary_action_label: __("Submit"),
			primary_action: async (values) => {
				await frappe.call({
					method: `${SP_MC_API}.submit_settlement`,
					args: { custody: c.name, ...values },
					freeze: true,
				});
				d.hide();
				this.refresh();
			},
		});
		d.show();
	}
}

$(`<style>
	.sp-mc-amount { font-size: var(--text-2xl); font-weight: var(--weight-semibold); }
	.sp-mc-card { border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: 12px 16px; margin-bottom: 12px; background: var(--card-bg); }
	.sp-mc-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>`).appendTo(document.head);
