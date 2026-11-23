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

// "HH:MM" for a number of seconds: time left rounds up (a new request shows 24:00), time
// overdue rounds down ("-HH:MM")
function sp_qq_hhmm(seconds) {
	const round = seconds < 0 ? Math.floor : Math.ceil;
	const minutes = round(Math.abs(seconds) / 60); // sp-allow-number: seconds per minute
	const hh = String(Math.floor(minutes / 60)).padStart(2, "0"); // sp-allow-number: minutes per hour
	const mm = String(minutes % 60).padStart(2, "0"); // sp-allow-number: minutes per hour
	return `${seconds < 0 ? "-" : ""}${hh}:${mm}`;
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
			const visit = r.site_visit_needed
				? ` <span class="indicator-pill orange">${esc(__("Site Visit Needed"))}</span>`
				: "";
			const $row = $(`<tr>
				<td><span class="indicator-pill sp-qq-clock ${colour}">${esc(__(r.state))}</span>
					<div class="text-muted small">${esc(__("{0} h", [r.hours]))}</div></td>
				<td>${esc(r.customer_name || "")}<div class="text-muted small">${esc(r.mobile || "")}</div></td>
				<td>${esc(r.system_type || "")}${visit}</td>
				<td class="small">${(r.key_data || []).map((d) => `<div>${esc(d)}</div>`).join("")}</td>
				<td>${(r.missing_fields || [])
					.map((m) => `<span class="indicator-pill red mr-1">${esc(m)}</span>`)
					.join("")}</td>
				<td>${esc(r.requested_by_name || "")}<div class="text-muted small">${esc(
					__(r.channel || "")
				)}</div></td>
				<td>${esc(r.follow_up_owner_name || "")}</td>
				<td>${esc(r.taken_by || "")}</td>
				<td class="text-right"></td>
			</tr>`);
			const $actions = $row.find("td:last");
			if (r.taken_by) {
				$(`<span class="indicator-pill blue mr-1"></span>`)
					.text(__("Taken by {0}", [r.taken_by]))
					.appendTo($actions);
			}
			// Take is off once someone has taken the request (or for anyone not a quote creator)
			$(`<button class="btn btn-xs btn-primary"></button>`)
				.text(__("Take"))
				.prop("disabled", !r.can_take)
				.on("click", () => r.can_take && this.take(r.name))
				.appendTo($actions);
			if (r.can_act) {
				const $menu = $(`<div class="btn-group ml-1">
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
				$(`<button class="btn btn-xs btn-default ml-1"></button>`)
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
	// last hours (Quote Amber After), red and negative once overdue.
	tick() {
		const passed = (Date.now() - this.loaded_at) / 1000; // sp-allow-number: ms per second
		this.$body.find(".sp-qq-clock").each((i, el) => {
			const r = $(el).data("row");
			if (r.seconds_left === null || r.seconds_left === undefined) return;
			const left = r.seconds_left - passed;
			let state = "On time";
			if (left <= 0) state = "Overdue";
			else if (r.amber_left && left <= r.amber_left) state = "Amber";
			$(el)
				.removeClass(Object.values(SP_QQ_COLOURS).join(" "))
				.addClass(SP_QQ_COLOURS[state])
				.text(`${sp_qq_hhmm(left)} · ${__(state)}`);
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
