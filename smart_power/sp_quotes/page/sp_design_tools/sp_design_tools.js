// T1 Design tools (SP-65): /app/sp-design-tools?quote=<quotation>. The page is a Vue bundle
// (public/js/design_tools); every figure comes from the server (smart_power.sp_quotes.design).
frappe.pages["sp-design-tools"].on_page_load = function (wrapper) {
	wrapper.sp_page = frappe.ui.make_app_page({ parent: wrapper, title: __("Design Tools"), single_column: true });
};

frappe.pages["sp-design-tools"].on_page_show = async function (wrapper) {
	const quote = frappe.utils.get_url_arg("quote") || frappe.route_options?.quote || "";
	frappe.route_options = null;
	await frappe.require("design_tools.bundle.js");
	sp.design_tools.mount(wrapper.sp_page, quote);
};
