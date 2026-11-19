// L1 Light field entry on the desk (SP-108): the winch manager logs for an operator.
// The rules and the posting are on the server (smart_power.sp_winch.field_entry).
const SP_FIELD_ENTRY_API = "smart_power.sp_winch.field_entry";

frappe.ui.form.on("SP Field Entry", {
	setup(frm) {
		frm.set_query("to_account", () => ({ query: `${SP_FIELD_ENTRY_API}.official_account_query` }));
		frm.set_query("on_behalf_of", () => ({ query: `${SP_FIELD_ENTRY_API}.operator_query` }));
		frm.set_query("station", () => ({ query: "smart_power.sp_winch.bookings.station_query" }));
		frm.set_query("internal_center", () => ({ query: "smart_power.sp_finance.queries.center_picker" }));
		frm.set_query("worker", () => ({ query: "smart_power.sp_core.workers.worker_query" }));
		frm.set_query("booking", () => ({ filters: { status: "Booked" } }));
		frm.set_query("related_job", () => ({ filters: { entry_kind: "Job", for_kind: "Outside" } }));
	},
	async booking(frm) {
		if (!frm.doc.booking) return;
		const { message: row } = await frappe.db.get_value("SP Vehicle Booking", frm.doc.booking, [
			"vehicle",
			"job_type",
			"for_kind",
			"station",
			"internal_center",
			"customer_name",
			"customer_phone",
			"place",
			"agreed_amount",
		]);
		await frm.set_value(row);
	},
});
