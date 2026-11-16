// The list pattern (SP-45): saved-view tabs ("Mine", "Open", "Overdue", "All" ... from SP List
// View, by role) above the list, and a totals bar for its money columns over every matching row
// (smart_power.lists). Frappe keeps the filter panel, columns, bulk actions and Excel export.
window.sp = window.sp || {};
sp.list = sp.list || {};

sp.list.tab_filters = function (doctype, view) {
	return (view.filters || []).map(([field, op, value]) => [
		doctype,
		field,
		op,
		value === "{user}" ? frappe.session.user : value,
	]);
};

sp.list.same = function (a, b) {
	const key = (rows) => JSON.stringify((rows || []).map((r) => r.slice(1, 4)).sort()); // sp-allow-number: a filter row is [doctype, field, op, value]
	return key(a) === key(b);
};

sp.list.render_tabs = function (listview) {
	const views = (frappe.boot.sp_list_views || {})[listview.doctype];
	if (!views || !views.length || listview.sp_no_tabs) return;
	let $tabs = listview.$page.find(".sp-list-tabs");
	if (!$tabs.length) {
		$tabs = $('<div class="sp-list-tabs d-flex gap-2 flex-wrap px-3 pt-2"></div>');
		listview.$frappe_list.before($tabs);
	}
	const current = listview.filter_area ? listview.filter_area.get() : [];
	const esc = frappe.utils.escape_html;
	$tabs.empty();
	views.forEach((view) => {
		const filters = sp.list.tab_filters(listview.doctype, view);
		const active = sp.list.same(filters, current);
		$(`<button class="btn btn-xs ${active ? "btn-primary" : "btn-default"}">${esc(__(view.label))}</button>`)
			.on("click", async () => {
				await listview.filter_area.clear(false);
				if (filters.length) await listview.filter_area.add(filters);
				else listview.refresh();
			})
			.appendTo($tabs);
	});
};

sp.list.render_totals = async function (listview) {
	const money = (listview.columns || [])
		.map((c) => c.df)
		.filter((df) => df && df.fieldtype === "Currency");
	// in the paging row, beside the page sizes: v16 sizes the results to leave room for that row
	const $paging = listview.$paging_area;
	let $bar = $paging.find(".sp-list-totals");
	if (!money.length) return $bar.remove();
	if (!$bar.length) $bar = $('<div class="sp-list-totals flex-grow-1 text-right px-3"></div>').insertBefore($paging.children(".level-right"));
	const { message } = await frappe.call({
		method: "smart_power.lists.totals",
		args: {
			doctype: listview.doctype,
			filters: listview.get_filters_for_args(),
			fields: money.map((df) => df.fieldname),
		},
		type: "GET",
	});
	const esc = frappe.utils.escape_html;
	$bar.html(
		`<b>${esc(__("Totals"))}</b> · ` +
			money
				.map((df) => `${esc(__(df.label))}: <b>${esc(format_currency((message || {})[df.fieldname] || 0))}</b>`)
				.join(" · ")
	);
};

$(document).on("app_ready", () => {
	const ListView = frappe.views && frappe.views.ListView;
	if (!ListView || ListView.prototype.sp_list_pattern) return;
	const after_render = ListView.prototype.after_render;
	ListView.prototype.after_render = function () {
		after_render.call(this);
		if (!(frappe.boot.sp_list_views || {})[this.doctype]) return;
		sp.list.render_tabs(this);
		sp.list.render_totals(this);
	};
	ListView.prototype.sp_list_pattern = true;
});
