// W4 Vehicles: how far each vehicle is from its oil change (SP-106).
frappe.listview_settings["Vehicle"] = {
	add_fields: ["sp_odometer_km", "sp_next_oil_km"],
	get_indicator(doc) {
		const left = (doc.sp_next_oil_km || 0) - (doc.sp_odometer_km || 0);
		return left < 0
			? [__("Oil change is {0} km late", [-left]), "red", "name,is,set"]
			: [__("{0} km to oil", [left]), "blue", "name,is,set"];
	},
};
