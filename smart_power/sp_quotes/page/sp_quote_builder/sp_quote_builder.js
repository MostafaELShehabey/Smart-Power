// Q2 Quote Builder (SP-57): /app/sp-quote-builder/<quotation>. The page itself is a Vue bundle
// (public/js/quote_builder); every total comes from the server (smart_power.sp_quotes.builder).
frappe.pages["sp-quote-builder"].on_page_load = function (wrapper) {
	wrapper.sp_page = frappe.ui.make_app_page({ parent: wrapper, title: __("Quote Builder"), single_column: true });
};

frappe.pages["sp-quote-builder"].on_page_show = async function (wrapper) {
	const name = frappe.get_route()[1];
	if (!name) {
		frappe.set_route("List", "Quotation");
		return;
	}
	const reload = !!frappe.route_options?.sp_reload; // the design tools pushed into it (SP-65)
	if (reload) frappe.route_options = null;
	await frappe.require("quote_builder.bundle.js");
	sp.quote_builder.mount(wrapper.sp_page, name, reload);
};
