// A3 Treasury (SP-116): every money account; who holds company cash and for how long. Days held
// past the limit are red. Each account opens its statement; an official account opens the bank
// reconciliation. Transfers (A4) come with SP-117. The rules are on the server
// (smart_power.sp_finance.treasury).

frappe.pages["sp-treasury"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Treasury"), single_column: true });
	wrapper.sp_treasury = new SPTreasury(page);
};

frappe.pages["sp-treasury"].on_page_show = function (wrapper) {
	wrapper.sp_treasury && wrapper.sp_treasury.refresh();
};

// the bank account the Reconcile button opens the tool with
let sp_treasury_reconcile = null;

frappe.ui.form.on("Bank Reconciliation Tool", {
	async refresh(frm) {
		if (!sp_treasury_reconcile) return;
		const { company, bank_account } = sp_treasury_reconcile;
		sp_treasury_reconcile = null;
		await frm.set_value("company", company);
		await frm.set_value("bank_account", bank_account);
	},
});

class SPTreasury {
	constructor(page) {
		this.page = page;
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.$body = $('<div class="sp-tr-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	async refresh() {
		const { message } = await frappe.call("smart_power.sp_finance.treasury.treasury");
		this.data = message;
		this.render();
	}

	statement(account) {
		frappe.set_route("query-report", "General Ledger", {
			company: this.data.company,
			account: [account],
			from_date: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			to_date: frappe.datetime.get_today(),
		});
	}

	reconcile(bank_account) {
		// the tool is a single form and ignores route options: the form hook below fills it
		sp_treasury_reconcile = { company: this.data.company, bank_account };
		frappe.set_route("Form", "Bank Reconciliation Tool");
	}

	render() {
		const esc = frappe.utils.escape_html;
		const money = (v, c) => esc(format_currency(v, c));
		this.$body.empty();
		const section = (title, total, rows, columns) => {
			const $s = $(`<div class="mb-4">
				<h5>${esc(title)} <span class="text-muted">${money(total)}</span></h5>
				<table class="table table-sm table-hover"><thead><tr>${columns
					.map((c) => `<th class="${c.right ? "text-right" : ""}">${esc(c.label)}</th>`)
					.join("")}<th></th></tr></thead><tbody></tbody></table>
			</div>`).appendTo(this.$body);
			if (!rows.length) {
				$s.find("tbody").append(`<tr><td colspan="${columns.length + 1}" class="text-muted">${esc(__("None"))}</td></tr>`);
			}
			rows.forEach((row) => {
				const $tr = $(`<tr class="${row.over ? "sp-tr-over" : ""}">${columns
					.map((c) => `<td class="${c.right ? "text-right" : ""}">${c.value(row)}</td>`)
					.join("")}<td class="text-nowrap"></td></tr>`).appendTo($s.find("tbody"));
				const $act = $tr.find("td:last");
				$(`<button class="btn btn-xs btn-default mr-1"></button>`)
					.text(__("Statement"))
					.on("click", () => this.statement(row.account))
					.appendTo($act);
				if (row.bank_account) {
					$(`<button class="btn btn-xs btn-default"></button>`)
						.text(__("Reconcile"))
						.on("click", () => this.reconcile(row.bank_account))
						.appendTo($act);
				}
			});
		};
		const name = { label: __("Account"), value: (r) => esc(r.account_name) };
		const balance = { label: __("Balance"), right: true, value: (r) => money(r.balance, r.currency) };
		const holder = { label: __("Holder"), value: (r) => esc(r.holder_name || "") };
		const days = {
			label: __("Days Held"),
			right: true,
			value: (r) =>
				r.days_held
					? `<span class="indicator-pill ${r.over ? "red" : "gray"}">${esc(__("{0} days", [r.days_held]))}</span>${
							r.limit ? ` <span class="small text-muted">/ ${esc(String(r.limit))}</span>` : ""
					  }`
					: "",
		};
		const t = this.data.totals;
		section(__("Official accounts"), t.official, this.data.official, [name, balance]);
		section(__("Cash with people"), t.transit, this.data.transit, [name, holder, balance, days]);
		section(__("Custody"), t.custody, this.data.custody, [name, holder, balance]);
	}
}

$(`<style>.sp-tr-over td { background: var(--bg-red); }</style>`).appendTo(document.head);
