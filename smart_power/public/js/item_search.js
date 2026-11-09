// Item search by words in any order (SP-29): item fields that use ERPNext's item query
// (quotes, orders, receipts, stock entries …) ask smart_power's wrapper instead. The
// wrapper keeps ERPNext's filters and results; the matching is on the server.
(() => {
	const ERPNEXT_ITEM_QUERY = "erpnext.controllers.queries.item_query";
	const SP_ITEM_QUERY = "smart_power.sp_stock.item_search.item_query";
	const Link = frappe.ui.form.ControlLink;
	if (!Link || Link.prototype.sp_item_search) return;
	const get_search_args = Link.prototype.get_search_args;
	Link.prototype.get_search_args = function (txt) {
		const args = get_search_args.call(this, txt);
		if (args && args.doctype === "Item" && args.query === ERPNEXT_ITEM_QUERY) {
			args.query = SP_ITEM_QUERY;
		}
		return args;
	};
	Link.prototype.sp_item_search = true;
})();
