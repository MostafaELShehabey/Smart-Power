// L1 Light field entry on the desk (SP-108): the winch manager logs for an operator.
// The rules and the posting are on the server (smart_power.sp_winch.field_entry).
const SP_FIELD_ENTRY_API = "smart_power.sp_winch.field_entry";
const SP_FIELD_LOCK_API = "smart_power.sp_winch.field_lock";

// A locked day (SP-109): the form says so, and the only action left is to ask to reopen it.
async function sp_show_lock(frm) {
	frm.set_intro();
	frm.remove_custom_button(__("Ask to Reopen"));
	frm.enable_save();
	if (!frm.doc.vehicle || !frm.doc.work_date) return;
	const { vehicle, work_date } = frm.doc;
	const { message: state } = await frappe.call({
		method: `${SP_FIELD_LOCK_API}.lock_state`,
		args: { vehicle, work_date },
	});
	if (!state.locked) return;
	if (state.blocked) frm.disable_save();
	if (state.request) {
		frm.set_intro(__("Day locked. Request {0} is waiting for a decision.", [state.request]), "orange");
		return;
	}
	frm.set_intro(__("Day locked"), "red");
	frm.add_custom_button(__("Ask to Reopen"), () => {
		frappe.prompt(
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
			async ({ reason }) => {
				await frappe.call({
					method: `${SP_FIELD_LOCK_API}.ask_to_reopen`,
					args: { vehicle, work_date, reason },
					freeze: true,
				});
				frappe.show_alert({ message: __("Sent for a decision"), indicator: "green" });
				sp_show_lock(frm);
			},
			__("Ask to Reopen"),
			__("Send")
		);
	});
}

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
	refresh: sp_show_lock,
	vehicle: sp_show_lock,
	work_date: sp_show_lock,
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
