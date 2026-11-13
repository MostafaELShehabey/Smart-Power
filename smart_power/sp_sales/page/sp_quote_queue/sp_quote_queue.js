// Q3 Quote request queue (SP-48): open requests, oldest first, with the 24 h quote clock.
// Green on time, amber soon due, red overdue. "Take" claims an unclaimed request.
// The rules are on the server (smart_power.sp_sales.quote_queue).

const SP_QQ_API = "smart_power.sp_sales.quote_queue";
const SP_QQ_VIEWS = [
	{ value: "Unclaimed", label: "Unclaimed" },
	{ value: "Mine", label: "Mine" },
	{ value: "All", label: "All" },
];
const SP_QQ_COLOURS = { "On time": "green", Amber: "orange", Overdue: "red", Sent: "blue" };

frappe.pages["sp-quote-queue"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Quote Request Queue"),
		single_column: true,
	});
	wrapper.sp_quote_queue = new SPQuoteQueue(page);
};

frappe.pages["sp-quote-queue"].on_page_show = function (wrapper) {
	wrapper.sp_quote_queue && wrapper.sp_quote_queue.refresh();
};

class SPQuoteQueue {
	constructor(page) {
		this.page = page;
		this.view = "Unclaimed";
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.$tabs = $('<div class="sp-qq-tabs btn-group mb-3"></div>').appendTo(this.page.main);
		SP_QQ_VIEWS.forEach((v) => {
			$(`<button class="btn btn-default btn-sm"></button>`)
				.text(__(v.label))
				.attr("data-view", v.value)
				.on("click", () => {
					this.view = v.value;
					this.refresh();
				})
				.appendTo(this.$tabs);
		});
		this.$body = $('<div class="sp-qq-body"></div>').appendTo(this.page.main);
		this.refresh();
	}

	async refresh() {
		this.$tabs.find("button").removeClass("btn-primary");
		this.$tabs.find(`button[data-view="${this.view}"]`).addClass("btn-primary");
		const { message: rows } = await frappe.call(`${SP_QQ_API}.get_queue`, { view: this.view });
		this.render(rows || []);
	}

	render(rows) {
		const esc = frappe.utils.escape_html;
		this.$body.empty();
		if (!rows.length) {
			this.$body.append(`<div class="text-muted p-4">${esc(__("No open requests here."))}</div>`);
			return;
		}
		const $table = $(`<table class="table table-hover sp-qq-table"><thead><tr>
			<th>${esc(__("Age"))}</th>
			<th>${esc(__("Customer"))}</th>
			<th>${esc(__("System Type"))}</th>
			<th>${esc(__("Channel"))}</th>
			<th>${esc(__("Requested By"))}</th>
			<th>${esc(__("Quote Creator"))}</th>
			<th></th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$body);
		const $tbody = $table.find("tbody");
		rows.forEach((r) => {
			const colour = SP_QQ_COLOURS[r.state] || "gray";
			const visit = r.site_visit_needed
				? ` <span class="indicator-pill orange">${esc(__("Site Visit Needed"))}</span>`
				: "";
			const $row = $(`<tr>
				<td><span class="indicator-pill ${colour}">${esc(__("{0} h", [r.hours]))} · ${esc(
					__(r.state)
				)}</span></td>
				<td>${esc(r.customer_name || "")}<div class="text-muted small">${esc(r.mobile || "")}</div></td>
				<td>${esc(r.system_type || "")}${visit}</td>
				<td>${esc(__(r.channel || ""))}</td>
				<td>${esc(r.requested_by || "")}</td>
				<td>${esc(r.quote_creator || "")}</td>
				<td class="text-right"></td>
			</tr>`);
			const $actions = $row.find("td:last");
			if (!r.quote_creator && r.status === "Quote request") {
				$(`<button class="btn btn-xs btn-primary"></button>`)
					.text(__("Take"))
					.on("click", () => this.take(r.name))
					.appendTo($actions);
			}
			$(`<button class="btn btn-xs btn-default ml-1"></button>`)
				.text(__("Open"))
				.on("click", () => frappe.set_route("Form", "SP Case", r.name))
				.appendTo($actions);
			$tbody.append($row);
		});
	}

	async take(name) {
		await frappe.call({ method: `${SP_QQ_API}.take`, args: { case: name }, freeze: true });
		frappe.show_alert({ message: __("Request {0} is yours", [name]), indicator: "green" });
		this.refresh();
	}
}
