// CL1 Collections (SP-81): every station I collect for, overdue first; its schedule, cheques due
// and their holder, and my last contact. Call (logged on the station), Record Payment (A2,
// pending the admin's confirmation) and Log Cheque (A5). The admin and the accountant see every
// collection owner and may filter. The rules are on the server (smart_power.sp_stations).

const SP_CL_API = "smart_power.sp_stations.collections";
const SP_CL_STATUS = { Paid: "green", Overdue: "red", Due: "blue" };

frappe.pages["sp-collections"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Collections"), single_column: true });
	wrapper.sp_collections = new SPCollections(page);
};

frappe.pages["sp-collections"].on_page_show = function (wrapper) {
	wrapper.sp_collections && wrapper.sp_collections.refresh();
};

class SPCollections {
	constructor(page) {
		this.page = page;
		this.owner = null;
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.$body = $('<div class="sp-cl-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_CL_API}.collections`, { owner: this.owner });
		this.data = message;
		this.owner_filter();
		this.render();
	}

	owner_filter() {
		if (!this.data.is_admin || this.owner_field) return;
		this.owner_field = this.page.add_field({
			fieldname: "owner",
			fieldtype: "Select",
			label: __("Collection Owner"),
			options: [{ value: "", label: __("All") }, ...this.data.owners],
			change: () => {
				this.owner = this.owner_field.get_value() || null;
				this.refresh();
			},
		});
	}

	render() {
		const esc = frappe.utils.escape_html;
		const money = (v) => esc(format_currency(v || 0));
		const date = (d) => (d ? esc(frappe.datetime.str_to_user(d)) : "");
		this.$body.empty();
		const t = this.data.totals;
		$(`<div class="sp-cl-totals mb-3">
			<span class="indicator-pill blue">${esc(__("Remaining"))}: ${money(t.remaining)}</span>
			<span class="indicator-pill ${t.overdue ? "red" : "gray"}">${esc(__("Overdue"))}: ${money(t.overdue)}
				· ${esc(__("Stations late: {0}", [t.overdue_stations]))}</span>
		</div>`).appendTo(this.$body);
		if (!this.data.stations.length) {
			$(`<div class="sp-cl-empty text-muted text-center p-5">${esc(__("No stations are assigned to you."))}</div>`).appendTo(
				this.$body
			);
			return;
		}
		this.data.stations.forEach((s) => {
			const $card = $(`<div class="sp-cl-card ${s.overdue_amount ? "sp-cl-late" : ""}">
				<div class="sp-cl-head">
					<div>
						<a class="sp-cl-customer" href="/app/sp-station/${encodeURIComponent(s.station)}">${esc(s.customer_name || s.customer)}</a>
						<span class="text-muted small">${esc(s.station)}</span>
					</div>
					<div class="sp-cl-actions"></div>
				</div>
				<div class="sp-cl-chips">
					<span>${esc(__("Remaining"))}: <b>${money(s.remaining)}</b></span>
					${
						s.overdue_amount
							? `<span class="text-danger">${esc(__("Overdue"))}: <b>${money(s.overdue_amount)}</b> · ${esc(
									__("{0} days", [s.overdue_days])
							  )}</span>`
							: ""
					}
					${
						s.next_due_date
							? `<span>${esc(__("Next Due"))}: ${money(s.next_due_amount)} · ${date(s.next_due_date)}</span>`
							: ""
					}
					${s.pending ? `<span class="text-muted">${esc(__("Pending Confirmation"))}: ${money(s.pending)}</span>` : ""}
				</div>
				<div class="sp-cl-contact small text-muted">${
					s.last_contact
						? esc(
								__("Last contact {0}: {1} ({2})", [ // sp-allow-number: placeholders
									frappe.datetime.prettyDate(s.last_contact.time),
									s.last_contact.result,
									s.last_contact.by,
								])
						  ) + (s.last_contact.note ? ` · ${esc(s.last_contact.note)}` : "")
						: esc(__("No contact yet"))
				}</div>
				<details class="sp-cl-more"><summary class="small">${esc(__("Schedule and cheques"))}</summary>
					<table class="table table-sm mt-2"><thead><tr>
						<th>${esc(__("Due Date"))}</th><th class="text-right">${esc(__("Amount"))}</th>
						<th class="text-right">${esc(__("Paid"))}</th><th class="text-right">${esc(__("Left"))}</th><th>${esc(__("Status"))}</th>
					</tr></thead><tbody>${s.schedule
						.map(
							(r) => `<tr><td>${date(r.due_date)}</td><td class="text-right">${money(r.amount)}</td>
							<td class="text-right">${money(r.paid)}</td><td class="text-right">${money(r.left)}</td>
							<td><span class="indicator-pill ${SP_CL_STATUS[r.status] || "gray"}">${esc(__(r.status))}</span></td></tr>`
						)
						.join("") || `<tr><td colspan="5" class="text-muted">${esc(__("No contract schedule yet"))}</td></tr>`}</tbody></table>
					${
						s.cheques.length
							? `<table class="table table-sm"><thead><tr><th>${esc(__("Cheque No."))}</th><th>${esc(__("Due Date"))}</th>
							<th class="text-right">${esc(__("Amount"))}</th><th>${esc(__("Status"))}</th><th>${esc(__("Holder"))}</th></tr></thead>
							<tbody>${s.cheques
								.map(
									(c) => `<tr><td><a href="/app/sp-cheque/${encodeURIComponent(c.name)}">${esc(c.cheque_no)}</a></td>
									<td>${date(c.due_date)}</td><td class="text-right">${money(c.amount)}</td>
									<td>${esc(__(c.status))}</td><td>${esc(c.holder ? frappe.user.full_name(c.holder) : "")}</td></tr>`
								)
								.join("")}</tbody></table>`
							: ""
					}
				</details>
			</div>`).appendTo(this.$body);
			if (s.cheques.some((c) => c.status === "Due" || c.status === "Bounced")) {
				$card.find(".sp-cl-more").attr("open", true);
			}
			const $act = $card.find(".sp-cl-actions");
			const button = (label, fn, primary) =>
				$(`<button class="btn btn-xs ${primary ? "btn-primary" : "btn-default"} ml-1"></button>`)
					.text(label)
					.on("click", fn)
					.appendTo($act);
			button(__("Call"), () => this.call(s), true);
			button(__("Record Payment"), () =>
				smart_power.record_payment_dialog({ station: s.station }, () => this.refresh())
			);
			if (frappe.model.can_create("SP Cheque")) {
				button(__("Log Cheque"), () => frappe.new_doc("SP Cheque", { station: s.station }));
			}
		});
	}

	call(s) {
		const dialog = new frappe.ui.Dialog({
			title: __("Call {0}", [s.customer_name || s.customer]),
			fields: [
				{
					fieldname: "result",
					fieldtype: "Link",
					label: __("Result"),
					options: "SP List Value",
					reqd: 1,
					get_query: () => ({ filters: { list_name: "Call Result", is_active: 1 } }),
				},
				{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
				{
					fieldname: "next_call_at",
					fieldtype: "Datetime",
					label: __("Next Call"),
					description: __("Becomes a call task for the collection owner."),
				},
			],
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				await frappe.call({
					method: `${SP_CL_API}.log_call`,
					args: { station: s.station, ...values },
					freeze: true,
				});
				dialog.hide();
				this.refresh();
			},
		});
		dialog.show();
	}
}

$(`<style>
	.sp-cl-card { border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: 12px 16px; margin-bottom: 12px; background: var(--card-bg); }
	.sp-cl-card.sp-cl-late { border-inline-start: 4px solid var(--red-500); }
	.sp-cl-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }
	.sp-cl-customer { font-weight: var(--weight-semibold); font-size: var(--text-lg); margin-inline-end: 6px; }
	.sp-cl-chips { display: flex; gap: 16px; flex-wrap: wrap; margin: 8px 0 4px; }
	.sp-cl-totals .indicator-pill { margin-inline-end: 8px; }
</style>`).appendTo(document.head);
