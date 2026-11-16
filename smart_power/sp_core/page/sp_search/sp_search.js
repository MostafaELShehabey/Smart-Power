// G5 Global search (SP-41): one box for a customer or mobile, a station, a request or quote, a
// purchase order, an item code or a cheque number. Results by kind, only what I may see
// (smart_power.search.global_search); five a kind, with "show all" to the filtered list.

frappe.pages["sp-search"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Search"), single_column: true });
	wrapper.sp_search = new SPSearch(page);
};

frappe.pages["sp-search"].on_page_show = function (wrapper) {
	const q = (frappe.route_options && frappe.route_options.q) || frappe.utils.get_url_arg("q") || "";
	frappe.route_options = null;
	wrapper.sp_search && wrapper.sp_search.show(q);
};

class SPSearch {
	constructor(page) {
		this.page = page;
		this.$input = $(`<input type="search" class="form-control input-lg mb-3" autocomplete="off"
			placeholder="${frappe.utils.escape_html(
				__("Customer or mobile, station, request or quote, PO, item code, cheque no.")
			)}">`).appendTo(this.page.main);
		this.$results = $('<div class="sp-search-results"></div>').appendTo(this.page.main);
		const run = frappe.utils.debounce(() => this.search(this.$input.val()), 250); // sp-allow-number: ms
		this.$input.on("input", run);
	}

	show(q) {
		if (q) this.$input.val(q);
		this.$input.trigger("focus");
		this.search(this.$input.val());
	}

	async search(q) {
		q = (q || "").trim();
		this.last = q;
		const esc = frappe.utils.escape_html;
		if (q.length < 2) { // sp-allow-number: the server's minimum
			this.$results.empty();
			return;
		}
		const { message } = await frappe.call({ method: "smart_power.search.global_search", args: { q }, type: "GET" });
		if (this.last !== q) return; // a newer search is on its way
		this.$results.empty();
		if (!message.groups.length) {
			$(`<div class="text-muted">${esc(__("Nothing found for {0}.", [q]))}</div>`).appendTo(this.$results);
			return;
		}
		message.groups.forEach((g) => {
			const $group = $(`<div class="mb-4">
				<div class="d-flex justify-content-between align-items-center mb-1">
					<h6 class="m-0">${esc(g.label)}</h6>
					<a href="#" class="small sp-search-more">${esc(__("Show all"))}</a>
				</div></div>`).appendTo(this.$results);
			$group.find(".sp-search-more").on("click", (e) => {
				e.preventDefault();
				frappe.route_options = g.more.route_options;
				frappe.set_route(...g.more.route);
			});
			g.results.forEach((r) =>
				$(`<div class="frappe-card p-2 mb-1" role="button">
					<div><b>${esc(r.title)}</b></div>
					<div class="text-muted small">${esc(r.subtitle)}</div></div>`)
					.on("click", () => frappe.set_route(...r.route))
					.appendTo($group)
			);
		});
	}
}
