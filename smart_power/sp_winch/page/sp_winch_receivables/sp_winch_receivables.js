// Winch receivables (SP-112): customers who owe for winch and Jumbo jobs, the oldest debt first,
// with their phone, open jobs, age and last follow-up note. Record a receipt or a note from here;
// the admin confirms Smart Power's own jobs. The rules are on the server
// (smart_power.sp_winch.receivables and receipts).

const SP_WRV_API = "smart_power.sp_winch.receivables";

frappe.pages["sp-winch-receivables"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Winch Receivables"),
		single_column: true,
	});
	wrapper.sp_winch_receivables = new SPWinchReceivables(page);
};

frappe.pages["sp-winch-receivables"].on_page_show = function (wrapper) {
	wrapper.sp_winch_receivables && wrapper.sp_winch_receivables.load();
};

class SPWinchReceivables {
	constructor(page) {
		this.page = page;
		this.page.add_inner_button(__("Refresh"), () => this.load());
		this.$summary = $('<div class="sp-wrv-summary mb-3"></div>').appendTo(this.page.main);
		this.$body = $('<div class="sp-wrv-body mb-4"></div>').appendTo(this.page.main);
		this.$confirm = $('<div class="sp-wrv-confirm"></div>').appendTo(this.page.main);
	}

	async load() {
		const { message } = await frappe.call(`${SP_WRV_API}.receivables`);
		this.data = message;
		this.render_summary();
		this.render_customers();
		if (message.can_confirm) this.load_to_confirm();
	}

	render_summary() {
		const esc = frappe.utils.escape_html;
		const d = this.data;
		this.$summary.html(`<div class="d-flex flex-wrap">
			<div class="mr-4"><div class="text-muted small">${esc(__("Customers"))}</div>
				<h4>${esc(String(d.customers.length))}</h4></div>
			<div class="mr-4"><div class="text-muted small">${esc(__("Open"))}</div>
				<h4>${esc(format_currency(d.total))}</h4></div>
			<div><div class="text-muted small">${esc(__("Debt Age Alert"))}</div>
				<h4>${
					d.debt_age_months
						? esc(__("{0} months", [d.debt_age_months]))
						: esc(__("Off"))
				}</h4></div>
		</div>`);
	}

	render_customers() {
		const esc = frappe.utils.escape_html;
		this.$body.empty();
		if (!this.data.customers.length) {
			this.$body.append(`<div class="text-muted p-4">${esc(__("Nobody owes for winch jobs."))}</div>`);
			return;
		}
		const $table = $(`<table class="table table-hover sp-wrv-table"><thead><tr>
			<th>${esc(__("Customer"))}</th><th>${esc(__("Phone"))}</th><th>${esc(__("Jobs"))}</th>
			<th class="text-right">${esc(__("Open"))}</th><th>${esc(__("Age"))}</th>
			<th>${esc(__("Last Note"))}</th><th></th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$body);
		this.data.customers.forEach((row) => {
			const note = row.last_note
				? `${esc(row.last_note.note)}<div class="small text-muted">${esc(row.last_note.by)} · ${esc(
						frappe.datetime.str_to_user(row.last_note.on)
				  )}</div>`
				: "";
			const jobs = row.jobs
				.map(
					(j) =>
						`<div class="small"><a href="/app/sp-field-entry/${encodeURIComponent(j.name)}">${esc(
							j.name
						)}</a> · ${esc(frappe.datetime.str_to_user(j.work_date))} · ${esc(
							format_currency(j.outstanding)
						)} <span class="text-muted">(${esc(__(j.status))})</span></div>`
				)
				.join("");
			const age = row.age_months
				? __("{0} months", [row.age_months])
				: __("{0} days", [row.age_days]);
			const $tr = $(`<tr class="${row.old ? "sp-wrv-old" : ""}">
				<td><a href="/app/customer/${encodeURIComponent(row.customer)}">${esc(row.customer_name || row.customer)}</a></td>
				<td>${row.phone ? `<a href="tel:${esc(row.phone)}">${esc(row.phone)}</a>` : ""}</td>
				<td>${jobs}</td>
				<td class="text-right">${esc(format_currency(row.outstanding))}</td>
				<td>${row.old ? '<span class="indicator-pill red">' : "<span>"}${esc(age)}</span></td>
				<td>${note}</td>
				<td class="text-nowrap"></td>
			</tr>`).appendTo($table.find("tbody"));
			const $actions = $tr.find("td:last");
			if (this.data.can_record) {
				this.button($actions, __("Record Receipt"), () =>
					frappe.new_doc("SP Winch Receipt", { customer: row.customer, amount: row.outstanding })
				, "btn-primary");
			}
			this.button($actions, __("Add Note"), () => this.note_dialog(row));
		});
	}

	button($cell, label, handler, style = "btn-default") {
		$(`<button class="btn btn-xs ${style} ml-1"></button>`).text(label).on("click", handler).appendTo($cell);
	}

	note_dialog(row) {
		const dialog = new frappe.ui.Dialog({
			title: __("Note on {0}", [row.customer_name || row.customer]),
			fields: [{ fieldname: "note", fieldtype: "Small Text", label: __("Note"), reqd: 1 }],
			primary_action_label: __("Save"),
			primary_action: async ({ note }) => {
				await frappe.call({
					method: `${SP_WRV_API}.add_note`,
					args: { customer: row.customer, note },
					freeze: true,
				});
				dialog.hide();
				this.load();
			},
		});
		dialog.show();
	}

	async load_to_confirm() {
		const esc = frappe.utils.escape_html;
		const { message: rows } = await frappe.call(`${SP_WRV_API}.to_confirm`);
		this.$confirm.empty();
		if (!rows.length) return;
		this.$confirm.append(`<h5 class="mb-2">${esc(__("Smart Power jobs to confirm"))}</h5>`);
		const $table = $(`<table class="table table-sm"><thead><tr>
			<th>${esc(__("Job"))}</th><th>${esc(__("For"))}</th><th>${esc(__("Vehicle"))}</th>
			<th class="text-right">${esc(__("Amount"))}</th><th></th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$confirm);
		rows.forEach((row) => {
			const $tr = $(`<tr>
				<td><a href="/app/sp-field-entry/${encodeURIComponent(row.name)}">${esc(row.name)}</a>
					<div class="small text-muted">${esc(frappe.datetime.str_to_user(row.work_date))}</div></td>
				<td>${esc(row.for || "")}</td><td>${esc(row.vehicle || "")}</td>
				<td class="text-right">${esc(format_currency(row.agreed))}</td><td></td>
			</tr>`).appendTo($table.find("tbody"));
			this.button($tr.find("td:last"), __("Confirm Job"), async () => {
				await frappe.call({
					method: "smart_power.sp_winch.receipts.confirm_jobs",
					args: { names: [row.name] },
					freeze: true,
				});
				this.load();
			}, "btn-primary");
		});
	}
}

$(`<style>
	.sp-wrv-old { background: var(--bg-red); }
	.sp-wrv-table td { vertical-align: top; }
</style>`).appendTo(document.head);
