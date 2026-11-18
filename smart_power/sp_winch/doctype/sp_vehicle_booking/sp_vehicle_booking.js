// W1 Winch and car bookings (SP-107). The rules are on the server (smart_power.sp_winch.bookings).
const SP_BOOKING_API = "smart_power.sp_winch.bookings";

frappe.ui.form.on("SP Vehicle Booking", {
	setup(frm) {
		frm.set_query("job_type", () => ({ filters: { list_name: "Job Type", is_active: 1 } }));
		frm.set_query("operator", () => ({ query: `${SP_BOOKING_API}.operator_query` }));
		frm.set_query("station", () => ({ query: `${SP_BOOKING_API}.station_query` }));
		frm.set_query("internal_center", () => ({ query: "smart_power.sp_finance.queries.center_picker" }));
	},
	refresh(frm) {
		if (frm.is_new() || ["Done", "Cancelled"].includes(frm.doc.status)) return;
		frm.add_custom_button(__("Cancel Booking"), () => {
			frappe.confirm(__("Cancel booking {0}?", [frm.doc.name]), async () => {
				await frappe.call({ method: `${SP_BOOKING_API}.cancel_booking`, args: { name: frm.doc.name }, freeze: true });
				frm.reload_doc();
			});
		});
	},
});
