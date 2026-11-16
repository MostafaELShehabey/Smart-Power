// G2 Home (SP-38): my numbers and my queue. The cards are the ones my roles' work needs
// (smart_power.dashboards.cards); a click opens the list with the same filter. Below, my queue:
// the inbox's open tasks and my to-dos, soonest first (smart_power.dashboards.queue).

frappe.pages["sp-home"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Home"), single_column: true });
	wrapper.sp_home = new SPHome(page);
};

frappe.pages["sp-home"].on_page_show = function (wrapper) {
	wrapper.sp_home && wrapper.sp_home.refresh();
};

class SPHome {
	constructor(page) {
		this.page = page;
		this.page.set_secondary_action(__("Refresh"), () => this.refresh());
		this.$cards = $('<div class="sp-home-cards"></div>').appendTo(this.page.main);
		$(`<h5 class="mt-4 mb-2">${frappe.utils.escape_html(__("My queue"))}</h5>`).appendTo(this.page.main);
		this.$queue = $('<div class="sp-home-queue"></div>').appendTo(this.page.main);
		frappe.realtime.on("sp_tasks", () => this.load_queue());
		$(document).on("sp_tasks_changed", () => this.load_queue());
	}

	refresh() {
		this.load_cards();
		this.load_queue();
	}

	async load_cards() {
		const { message } = await frappe.call("smart_power.dashboards.cards.get_home");
		const esc = frappe.utils.escape_html;
		this.$cards.empty();
		if (!message.cards.length) {
			$(`<div class="text-muted">${esc(__("No numbers for your work yet."))}</div>`).appendTo(this.$cards);
			return;
		}
		message.cards.forEach((c) => {
			const value = c.fieldtype === "Currency" ? format_currency(c.value) : format_number(c.value, null, 0);
			$(`<div class="sp-home-card frappe-card indicator-border-${esc(c.indicator)}" role="button" tabindex="0">
				<div class="sp-home-card-label text-muted">${esc(c.label)}</div>
				<div class="sp-home-card-value indicator-pill ${esc(c.indicator)}">${esc(value)}</div>
				<div class="sp-home-card-note small text-muted">${esc(c.note || "")}</div>
			</div>`)
				.on("click", () => this.open(c))
				.appendTo(this.$cards);
		});
	}

	open(c) {
		if (c.route_options) frappe.route_options = c.route_options;
		frappe.set_route(...c.route);
	}

	async load_queue() {
		const { message: rows } = await frappe.call("smart_power.dashboards.queue.get_my_queue");
		const esc = frappe.utils.escape_html;
		this.$queue.empty();
		if (!rows.length) {
			$(`<div class="text-muted">${esc(__("Nothing waiting for you."))}</div>`).appendTo(this.$queue);
			return;
		}
		rows.forEach((r) => {
			const due = r.due ? ` · ${esc(__("Due"))}: ${esc(frappe.datetime.str_to_user(r.due))}` : "";
			const $row = $(`<div class="frappe-card p-2 mb-1 d-flex align-items-center gap-2" role="button">
				${r.high ? `<span class="indicator-pill red">${esc(__("High"))}</span>` : ""}
				<span class="flex-grow-1">${esc(r.title)}</span>
				<span class="text-muted small"><span class="indicator-pill gray">${esc(__(r.kind))}</span>${due}</span>
			</div>`).appendTo(this.$queue);
			if (r.doctype && r.name) $row.on("click", () => frappe.set_route("Form", r.doctype, r.name));
		});
	}
}
