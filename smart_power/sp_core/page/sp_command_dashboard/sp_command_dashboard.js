// AD1 Command dashboard (SP-138): money, sales, operations and centers for a month, and the list
// of what waits for the admin. Every number opens the list or report behind it, with the same
// filter. The numbers are on the server (smart_power.dashboards.command).

const SP_CD_MONTHS = 12; // sp-allow-number: the months the selector offers, this one and the 11 before

frappe.pages["sp-command-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Command Dashboard"),
		single_column: true,
	});
	wrapper.sp_command_dashboard = new SPCommandDashboard(page);
};

frappe.pages["sp-command-dashboard"].on_page_show = function (wrapper) {
	wrapper.sp_command_dashboard && wrapper.sp_command_dashboard.refresh();
};

class SPCommandDashboard {
	constructor(page) {
		this.page = page;
		const today = frappe.datetime.get_today();
		const months = [];
		for (let i = 0; i < SP_CD_MONTHS; i++) {
			months.push(frappe.datetime.add_months(today, -i).slice(0, 7)); // sp-allow-number: "YYYY-MM"
		}
		this.month_field = this.page.add_field({
			fieldname: "month",
			fieldtype: "Select",
			label: __("Month"),
			options: months,
			default: months[0],
			change: () => this.refresh(),
		});
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
		this.$body = $('<div class="sp-cd-body"></div>').appendTo(this.page.main);
	}

	async refresh() {
		const { message } = await frappe.call("smart_power.dashboards.command.get", {
			month: this.month_field.get_value(),
		});
		this.data = message;
		this.render();
	}

	open(c) {
		if (!c.route || !c.route.length) return;
		frappe.route_options = Object.keys(c.route_options || {}).length ? c.route_options : null;
		frappe.set_route(...c.route);
	}

	value(c) {
		if (c.fieldtype === "Currency") return format_currency(c.value);
		if (c.fieldtype === "Percent") return `${format_number(c.value, null, 1)}%`;
		return format_number(c.value, null, 0);
	}

	cards($parent, cards) {
		const esc = frappe.utils.escape_html;
		const $row = $('<div class="sp-cd-cards"></div>').appendTo($parent);
		cards.forEach((c) => {
			$(`<div class="sp-cd-card frappe-card indicator-border-${esc(c.indicator)}" role="button" tabindex="0"
				data-key="${esc(c.key)}">
				<div class="small text-muted">${esc(c.label)}</div>
				<div class="sp-cd-value">${esc(this.value(c))}</div>
				<div class="small text-muted">${esc(c.note || "")}</div>
			</div>`)
				.on("click", () => this.open(c))
				.appendTo($row);
		});
		return $row;
	}

	table($parent, columns, rows, on_click) {
		const esc = frappe.utils.escape_html;
		const $t = $(`<table class="table table-sm table-hover mb-0"><thead><tr>${columns
			.map((c) => `<th class="${c.right ? "text-right" : ""}">${esc(c.label)}</th>`)
			.join("")}</tr></thead><tbody></tbody></table>`).appendTo($parent);
		if (!rows.length) {
			$t.find("tbody").append(`<tr><td colspan="${columns.length}" class="text-muted">${esc(__("None"))}</td></tr>`);
		}
		rows.forEach((r) => {
			const $tr = $(`<tr class="${r.over ? "sp-cd-over" : ""}">${columns
				.map((c) => `<td class="${c.right ? "text-right" : ""}">${c.value(r)}</td>`)
				.join("")}</tr>`).appendTo($t.find("tbody"));
			if (on_click) $tr.attr("role", "button").on("click", () => on_click(r));
		});
	}

	section(title) {
		const esc = frappe.utils.escape_html;
		const $s = $(`<div class="sp-cd-section mb-4"><h5 class="mb-2">${esc(title)}</h5></div>`).appendTo(this.$body);
		return $s;
	}

	chart($parent, type, labels, values, name) {
		if (!values.some((v) => v)) return;
		const $c = $('<div class="sp-cd-chart frappe-card p-2 mt-2"></div>').appendTo($parent);
		new frappe.Chart($c[0], {
			type,
			height: 220, // sp-allow-number: chart height in pixels
			data: { labels, datasets: [{ name, values }] },
		});
	}

	render() {
		const esc = frappe.utils.escape_html;
		const money = (v) => esc(format_currency(v));
		const d = this.data;
		this.$body.empty();
		const treasury = () => frappe.set_route("sp-treasury");

		d.sections.forEach((s) => {
			const $s = this.section(s.label);
			this.cards($s, s.cards);
			if (s.key === "money") {
				const $grid = $('<div class="row mt-2"></div>').appendTo($s);
				const $a = $('<div class="col-md-6"></div>').appendTo($grid);
				const $b = $('<div class="col-md-6"></div>').appendTo($grid);
				$a.append(`<div class="small text-muted mb-1">${esc(__("Official accounts"))}</div>`);
				this.table(
					$a,
					[
						{ label: __("Account"), value: (r) => esc(r.account_name) },
						{ label: __("Balance"), right: true, value: (r) => money(r.balance) },
					],
					d.official,
					treasury
				);
				$b.append(`<div class="small text-muted mb-1">${esc(__("Cash with people"))}</div>`);
				this.table(
					$b,
					[
						{ label: __("Holder"), value: (r) => esc(r.holder_name || r.account_name) },
						{ label: __("Balance"), right: true, value: (r) => money(r.balance) },
						{
							label: __("Days Held"),
							right: true,
							value: (r) =>
								`<span class="indicator-pill ${r.over ? "red" : "gray"}">${esc(
									__("{0} days", [r.days_held])
								)}</span>`,
						},
					],
					d.transit,
					treasury
				);
			}
			if (s.key === "sales") {
				this.chart(
					$s,
					"bar",
					d.channels.map((c) => c.label),
					d.channels.map((c) => c.requests),
					__("Requests")
				);
			}
			if (s.key === "operations") {
				this.chart(
					$s,
					"donut",
					d.statuses.map((c) => c.label),
					d.statuses.map((c) => c.count),
					__("Stations")
				);
			}
		});

		const $c = this.section(__("Centers"));
		this.table(
			$c,
			[
				{ label: __("Center"), value: (r) => esc(r.label) },
				{ label: __("Revenue"), right: true, value: (r) => money(r.revenue) },
				{ label: __("Cost"), right: true, value: (r) => money(r.cost) },
				{
					label: __("Profit"),
					right: true,
					value: (r) => `<span class="${r.profit < 0 ? "text-danger" : ""}">${money(r.profit)}</span>`,
				},
			],
			d.centers,
			(r) => this.open(r)
		);
		$c.append(`<div class="small text-muted mt-3 mb-1">${esc(__("Stations closed this month: estimate vs actual"))}</div>`);
		this.table(
			$c,
			[
				{ label: __("Station"), value: (r) => `${esc(r.station)} <span class="text-muted">${esc(r.customer_name || "")}</span>` },
				{ label: __("Estimated Profit"), right: true, value: (r) => money(r.estimate) },
				{ label: __("Actual Profit"), right: true, value: (r) => money(r.actual) },
				{
					label: __("Difference"),
					right: true,
					value: (r) => `<span class="${r.difference < 0 ? "text-danger" : ""}">${money(r.difference)}</span>`,
				},
			],
			d.projects,
			(r) => frappe.set_route("Form", "SP Station", r.station)
		);

		const $att = this.section(__("Needs your attention"));
		this.cards($att, d.attention);
	}
}

$(`<style>
	.sp-cd-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--padding-sm); }
	.sp-cd-card { padding: var(--padding-sm) var(--padding-md); border-inline-start: 3px solid var(--gray-400); }
	.sp-cd-card.indicator-border-red { border-inline-start-color: var(--red-500); }
	.sp-cd-card.indicator-border-orange { border-inline-start-color: var(--orange-500); }
	.sp-cd-card.indicator-border-green { border-inline-start-color: var(--green-500); }
	.sp-cd-card.indicator-border-blue { border-inline-start-color: var(--blue-500); }
	.sp-cd-value { font-size: var(--text-xl); font-weight: var(--weight-semibold); }
	.sp-cd-over td { background: var(--bg-red); }
</style>`).appendTo(document.head);
