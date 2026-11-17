// PR1 programming and commissioning (SP-97): pick the station's system, fill the readings and the
// checklist from its template, the latest settings file of the inverter's brand and model is
// suggested (SP-98), and each component's warranty comes from its item. The rules are on the
// server (smart_power.sp_site.commissioning).
const SP_COM_API = "smart_power.sp_site.commissioning";

frappe.ui.form.on("SP Commissioning", {
	setup(frm) {
		frm.set_query("settings_file", () => ({
			filters: { brand: frm.doc.inverter_brand || "", model: frm.doc.inverter_model || "" },
		}));
	},

	refresh(frm) {
		sp_com_systems(frm);
		if (frm.doc.station) {
			frm.add_custom_button(__("Station"), () => frappe.set_route("Form", "SP Station", frm.doc.station), __("View"));
		}
	},

	station(frm) {
		frm.set_value("system_row", "");
		sp_com_systems(frm);
	},

	async system_row(frm) {
		if (!frm.is_new() || !frm.doc.system_row) return;
		const system = (frm.sp_systems || []).find((s) => s.value === frm.doc.system_row);
		const { message } = await frappe.call(`${SP_COM_API}.defaults_for`, { system_type: system?.system_type });
		// a fresh start from the system's template, unless something was ticked already
		if (!(frm.doc.checklist || []).some((r) => r.done)) {
			frm.clear_table("checklist");
			message.checklist.forEach((r) => frm.add_child("checklist", r));
			frm.refresh_field("checklist");
		}
		if (!(frm.doc.readings || []).some((r) => r.value)) {
			frm.clear_table("readings");
			message.readings.forEach((r) => frm.add_child("readings", r));
			frm.refresh_field("readings");
		}
	},

	inverter_brand: (frm) => sp_com_suggest_settings(frm),
	inverter_model: (frm) => sp_com_suggest_settings(frm),
});

frappe.ui.form.on("SP Station Component", {
	async item(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item || row.warranty_months) return;
		const { message } = await frappe.call(`${SP_COM_API}.item_warranty_months`, { item_code: row.item });
		if (message) frappe.model.set_value(cdt, cdn, "warranty_months", message);
	},
});

async function sp_com_systems(frm) {
	if (!frm.doc.station) {
		frm.set_df_property("system_row", "options", [""]);
		return;
	}
	const { message: systems } = await frappe.call(`${SP_COM_API}.station_systems`, { station: frm.doc.station });
	frm.sp_systems = systems;
	const options = systems
		.filter((s) => !s.done || s.value === frm.doc.system_row)
		.map((s) => ({ value: s.value, label: s.label }));
	frm.set_df_property("system_row", "options", [{ value: "", label: "" }, ...options]);
	frm.toggle_reqd("system_row", systems.length > 0);
	frm.toggle_display("system_row", systems.length > 0);
	// a new commissioning for a station with one system left takes it
	if (frm.is_new() && !frm.doc.system_row && options.length === 1) {
		frm.set_value("system_row", options[0].value);
	}
}

async function sp_com_suggest_settings(frm) {
	if (frm.doc.docstatus || !frm.doc.inverter_brand || !frm.doc.inverter_model) return;
	const { message: latest } = await frappe.call("smart_power.sp_site.settings_files.latest", {
		brand: frm.doc.inverter_brand,
		model: frm.doc.inverter_model,
	});
	if (latest && frm.doc.settings_file !== latest.name) {
		frm.set_value("settings_file", latest.name);
		frappe.show_alert({ message: __("Latest settings file: {0}", [latest.title]), indicator: "blue" });
	} else if (!latest && frm.doc.settings_file) {
		frm.set_value("settings_file", "");
	}
}
