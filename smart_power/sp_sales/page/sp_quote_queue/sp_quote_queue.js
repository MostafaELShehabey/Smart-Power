// Q3 Quote request queue (SP-48): open requests, oldest first, with the 24 h quote clock.
// Green on time, amber soon due, red overdue. "Take" claims an unclaimed request; every quote
// creator sees every open request, a taken one marked with who took it.
// The rules are on the server (smart_power.sp_sales.quote_queue).

const SP_QQ_API = "smart_power.sp_sales.quote_queue";
const SP_QQ_VIEWS = [
	{ value: "Unclaimed", label: "Unclaimed" },
	{ value: "Mine", label: "Mine" },
	{ value: "All", label: "All" },
	{ value: "Overdue", label: "Overdue" }, // AD1's "requests over 24 h" opens here (SP-138)
];
const SP_QQ_COLOURS = { "On time": "green", Amber: "orange", Overdue: "red", Sent: "blue" };
const SP_QQ_TICK_MS = 30000; // sp-allow-number: the countdown redraws every 30 seconds

// "HH:MM" for a number of seconds, without a sign: time left rounds up (a new request shows
// 24:00), time overdue rounds down. The clock's words say which of the two it is (BUG-36).
function sp_qq_hhmm(seconds) {
	const round = seconds < 0 ? Math.floor : Math.ceil;
	const minutes = round(Math.abs(seconds) / 60); // sp-allow-number: seconds per minute
	const hh = String(Math.floor(minutes / 60)).padStart(2, "0"); // sp-allow-number: minutes per hour
	const mm = String(minutes % 60).padStart(2, "0"); // sp-allow-number: minutes per hour
	return `${hh}:${mm}`;
}

frappe.pages["sp-quote-queue"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Quote Request Queue"),
		single_column: true,
	});
	wrapper.sp_quote_queue = new SPQuoteQueue(page);
};

frappe.pages["sp-quote-queue"].on_page_show = function (wrapper) {
	const view = frappe.route_options && frappe.route_options.view;
	frappe.route_options = null;
	if (!wrapper.sp_quote_queue) return;
	if (view && SP_QQ_VIEWS.some((v) => v.value === view)) wrapper.sp_quote_queue.view = view;
	wrapper.sp_quote_queue.refresh();
};

class SPQuoteQueue {
	constructor(page) {
		this.page = page;
		this.view = "All";
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
		this.add_styles();
		this.refresh();
	}

	// One line per clock, title and button row, so no cell breaks into its neighbour (BUG-36)
	add_styles() {
		if (document.getElementById("sp-qq-style")) return;
		$(`<style id="sp-qq-style">
			.sp-qq-table th, .sp-qq-table .sp-qq-nowrap, .sp-qq-table .indicator-pill { white-space: nowrap; }
			.sp-qq-table td { vertical-align: middle; }
			.sp-qq-table th:last-child, .sp-qq-table td:last-child { width: 1%; }
			.sp-qq-missing { display: flex; flex-wrap: wrap; gap: var(--padding-xs); }
			.sp-qq-actions { display: flex; flex-wrap: nowrap; gap: var(--padding-xs);
				justify-content: flex-end; white-space: nowrap; }
		</style>`).appendTo(document.head);
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
			<th>${esc(__("Countdown"))}</th>
			<th>${esc(__("Customer"))}</th>
			<th>${esc(__("System Type"))}</th>
			<th>${esc(__("Key Data"))}</th>
			<th>${esc(__("Missing Fields"))}</th>
			<th>${esc(__("Requested By"))}</th>
			<th>${esc(__("Follow-up Owner"))}</th>
			<th>${esc(__("Quote Creator"))}</th>
			<th></th>
		</tr></thead><tbody></tbody></table>`).appendTo(this.$body);
		const $tbody = $table.find("tbody");
		rows.forEach((r) => {
			const colour = SP_QQ_COLOURS[r.state] || "gray";
			// a submitted survey is done: the quote creator need not wait for it (BUG-5)
			const visit =
				r.survey === "Done"
					? `<div><span class="indicator-pill green">${esc(__("Site Survey Done"))}</span></div>`
					: r.site_visit_needed || r.survey
					? `<div><span class="indicator-pill orange">${esc(__("Site Visit Needed"))}</span></div>`
					: "";
			const $row = $(`<tr>
				<td class="sp-qq-nowrap"><span class="indicator-pill sp-qq-clock ${colour}"
					title="${esc(__("Requested {0} h ago", [r.hours]))}">${esc(__(r.state))}</span></td>
				<td>${esc(r.customer_name || "")}<div class="text-muted small">${esc(r.mobile || "")}</div></td>
				<td>${esc(r.system_type || "")}${visit}</td>
				<td class="small sp-qq-nowrap">${(r.key_data || [])
					.map((d) => `<div>${esc(d)}</div>`)
					.join("")}</td>
				<td><div class="sp-qq-missing">${(r.missing_fields || [])
					.map((m) => `<span class="indicator-pill red">${esc(m)}</span>`)
					.join("")}</div></td>
				<td>${esc(r.requested_by_name || "")}<div class="text-muted small">${esc(
					__(r.channel || "")
				)}</div></td>
				<td>${esc(r.follow_up_owner_name || "")}</td>
				<td>${esc(r.taken_by || "")}</td>
				<td><div class="sp-qq-actions"></div></td>
			</tr>`);
			// Always in this order: Take, Actions, Open. Who took a request is in "Quote Creator".
			const $actions = $row.find(".sp-qq-actions");
			// Take is offered only while the request is free, and only to a quote creator
			if (r.can_take) {
				$(`<button class="btn btn-xs btn-primary"></button>`)
					.text(__("Take"))
					.on("click", () => this.take(r.name))
					.appendTo($actions);
			}
			if (r.can_act) {
				const $menu = $(`<div class="btn-group">
					<button class="btn btn-xs btn-default dropdown-toggle" data-toggle="dropdown"></button>
					<div class="dropdown-menu dropdown-menu-right"></div>
				</div>`).appendTo($actions);
				$menu.find("button").text(__("Actions"));
				const add = (label, fn) =>
					$(`<a class="dropdown-item" href="#"></a>`)
						.text(label)
						.on("click", (e) => {
							e.preventDefault();
							fn();
						})
						.appendTo($menu.find(".dropdown-menu"));
				add(__("Start the Quote"), () => this.start_quote(r.name));
				add(__("Ask for Missing Data"), () => this.ask_missing_data(r));
				add(__("Ask for a Site Survey"), () => this.ask_site_survey(r.name));
			}
			if (r.can_open) {
				$(`<button class="btn btn-xs btn-default"></button>`)
					.text(__("Open", null, "action"))
					.on("click", () => frappe.set_route("Form", "SP Case", r.name))
					.appendTo($actions);
			}
			$row.find(".sp-qq-clock").data("row", r);
			$tbody.append($row);
		});
		this.loaded_at = Date.now();
		this.tick();
		clearInterval(this.timer);
		this.timer = setInterval(() => this.tick(), SP_QQ_TICK_MS);
	}

	// The 24 h countdown, from the seconds left when the queue loaded: green, amber in the
	// last hours (Quote Amber After), red once overdue. It reads "05:12 left" or "Overdue 225:56";
	// the digits keep their own direction inside the Arabic words.
	tick() {
		const passed = (Date.now() - this.loaded_at) / 1000; // sp-allow-number: ms per second
		this.$body.find(".sp-qq-clock").each((i, el) => {
			const r = $(el).data("row");
			if (r.seconds_left === null || r.seconds_left === undefined) return;
			const left = r.seconds_left - passed;
			let state = "On time";
			if (left <= 0) state = "Overdue";
			else if (r.amber_left && left <= r.amber_left) state = "Amber";
			const time = `<bdi dir="ltr">${sp_qq_hhmm(left)}</bdi>`;
			$(el)
				.removeClass(Object.values(SP_QQ_COLOURS).join(" "))
				.addClass(SP_QQ_COLOURS[state])
				.html(`<span>${left <= 0 ? __("Overdue {0}", [time]) : __("{0} left", [time])}</span>`);
		});
	}

	async take(name) {
		await frappe.call({ method: `${SP_QQ_API}.take`, args: { case: name }, freeze: true });
		frappe.show_alert({ message: __("Request {0} is yours", [name]), indicator: "green" });
		this.refresh();
	}

	async start_quote(name) {
		const { message } = await frappe.call({
			method: `${SP_QQ_API}.start_quote`,
			args: { case: name },
			freeze: true,
		});
		frappe.set_route("sp-quote-builder", message.quotation);
	}

	ask_missing_data(r) {
		const dialog = new frappe.ui.Dialog({
			title: __("Ask for Missing Data"),
			fields: [
				{
					fieldname: "message",
					fieldtype: "Small Text",
					label: __("What is missing?"),
					reqd: 1,
					default: (r.missing_fields || []).join(", "),
				},
			],
			primary_action_label: __("Send"),
			primary_action: async ({ message }) => {
				await frappe.call({
					method: `${SP_QQ_API}.ask_missing_data`,
					args: { case: r.name, message },
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("The requester was asked"), indicator: "green" });
			},
		});
		dialog.show();
	}

	async ask_site_survey(name) {
		const { message: count } = await frappe.call({
			method: `${SP_QQ_API}.ask_site_survey`,
			args: { case: name },
			freeze: true,
		});
		frappe.show_alert({
			message: __("{0} installation manager(s) asked", [count]),
			indicator: "green",
		});
	}
}
