// SH2 (SP-104): the box's day to work on, the open one or today's.
frappe.listview_settings["SP Cash Box Day"] = {
	onload(list) {
		list.page.add_inner_button(__("Today's Cash Box"), async () => {
			const name = await frappe.xcall("smart_power.sp_finance.cash_box.open_today");
			frappe.set_route("Form", "SP Cash Box Day", name);
		});
	},
};
