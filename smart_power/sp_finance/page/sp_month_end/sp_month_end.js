// A14 Month close (SP-126): the month's checklist with live status, then the admin closes it; a
// red check needs a reason. A closed month refuses every entry dated in it until the admin reopens
// it with a reason. The rules are on the server (smart_power.sp_finance.month_close).
const SP_ME_API = "smart_power.sp_finance.month_close";
const SP_ME_MONTH_FROM = 3; // sp-allow-number: "dd-mm-yyyy" without the day
const SP_ME_COLOURS = { Green: "green", Red: "red", Grey: "gray" };

frappe.pages["sp-month-end"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Month Close"), single_column: true });
	frappe.pages["sp-month-end"].sp_month_end = new SPMonthEnd(page);
};

class SPMonthEnd {
	constructor(page) {
		this.page = page;
		const last = frappe.datetime.add_months(frappe.datetime.month_start(), -1);
		this.month = this.page.add_field({
			fieldname: "month",
			fieldtype: "Date",
			label: __("Month"),
			default: last,
			change: () => this.refresh(),
		});
		this.$body = $('<div class="sp-me-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	async refresh() {
		const month = this.month.get_value();
		if (!month) return;
		const { message } = await frappe.call(`${SP_ME_API}.checklist`, { month });
		this.data = message;
		this.render();
	}

	render() {
		const esc = frappe.utils.escape_html;
		const d = this.data;
		const closed = d.status === "Closed";
		const label = frappe.datetime.str_to_user(d.month).slice(SP_ME_MONTH_FROM);
		this.page.clear_primary_action();
		this.page.clear_secondary_action();
		const head = closed
			? `<div class="alert alert-success">${esc(__("{0} is closed", [label]))} · ${esc(
					d.closed_by ? (frappe.user_info(d.closed_by) || {}).fullname : ""
				)} · ${esc(frappe.datetime.str_to_user(d.closed_on || ""))}</div>`
			: `<div class="alert alert-warning">${esc(__("{0} is open", [label]))}</div>`;
		const rows = (closed && d.closed_checks.length ? d.closed_checks : d.checks)
			.map((c, i) => {
				const link = c.route ? `<a class="sp-me-link" data-i="${i}">${esc(__("Open the list"))}</a>` : "";
				const reason =
					!closed && c.status === "Red"
						? `<input class="form-control input-xs sp-me-reason" data-key="${esc(c.key)}" placeholder="${esc(
								__("Reason to close anyway")
							)}">`
						: esc(c.override_reason || "");
				return `<tr><td><span class="indicator-pill ${SP_ME_COLOURS[c.status] || "gray"}">${esc(
					__(c.status === "Green" ? "Done" : c.status === "Red" ? "Not done" : "Not built yet")
				)}</span></td><td>${esc(c.label)}</td><td class="text-right">${c.count || ""}</td>
					<td class="small text-muted">${esc(c.details || "")}</td><td>${link}</td><td>${reason}</td></tr>`;
			})
			.join("");
		const reopens = (d.reopens || [])
			.map(
				(r) =>
					`<li>${esc(frappe.datetime.str_to_user(r.reopened_on))} · ${esc((frappe.user_info(r.reopened_by) || {}).fullname)}: ${esc(r.reason)}</li>`
			)
			.join("");
		this.$body.html(`${head}
			<table class="table table-sm"><thead><tr><th></th><th>${esc(__("Checklist Item"))}</th><th class="text-right">${esc(
				__("Count")
			)}</th><th>${esc(__("Details"))}</th><th></th><th>${esc(__("Acknowledged Because"))}</th></tr></thead>
			<tbody>${rows}</tbody></table>
			${reopens ? `<h6>${esc(__("Reopened"))}</h6><ul class="small">${reopens}</ul>` : ""}
			<div class="small text-muted">${esc(
				__("A closed month refuses every entry dated in it, for everyone, until the admin reopens it.")
			)}</div>`);
		this.$body.find(".sp-me-link").on("click", (e) => {
			const c = d.checks[e.currentTarget.dataset.i];
			if (c.route.options) frappe.route_options = c.route.options;
			frappe.set_route(...c.route.route);
		});
		if (closed) {
			this.page.set_secondary_action(__("Reopen"), () => this.reopen());
		} else if (d.ended) {
			this.page.set_primary_action(__("Close the Month"), () => this.close());
		}
	}

	close() {
		const reasons = {};
		this.$body.find(".sp-me-reason").each((_i, el) => {
			reasons[el.dataset.key] = el.value;
		});
		const label = frappe.datetime.str_to_user(this.data.month).slice(SP_ME_MONTH_FROM);
		frappe.confirm(__("Close {0}? Nothing dated in it can be posted until it is reopened.", [label]), async () => {
			await frappe.call({ method: `${SP_ME_API}.close_month`, args: { month: this.data.month, reasons }, freeze: true });
			frappe.show_alert({ message: __("{0} is closed", [label]), indicator: "green" });
			this.refresh();
		});
	}

	reopen() {
		frappe.prompt(
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
			async ({ reason }) => {
				await frappe.call({ method: `${SP_ME_API}.reopen_month`, args: { month: this.data.month, reason }, freeze: true });
				this.refresh();
			},
			__("Reopen"),
			__("Reopen")
		);
	}
}
