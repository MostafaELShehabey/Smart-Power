// S2 / TK1 site tasks (SP-100): the technician checks in on site (time and location) and marks
// the task done with the hours; photos are the task's attachments. The rules are on the server.
const SP_TASK_API = "smart_power.sp_site.site_tasks";

frappe.ui.form.on("Task", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.sp_station || ["Completed", "Cancelled"].includes(frm.doc.status)) return;
		if (!frm.doc.sp_checkin_at) {
			frm.add_custom_button(__("Check In"), () => sp_task_check_in(frm)).addClass("btn-primary");
		}
		frm.add_custom_button(__("Mark Done"), () => {
			frappe.prompt(
				[{ fieldname: "hours", fieldtype: "Float", label: __("Hours on Site"), default: frm.doc.sp_hours }],
				async (values) => {
					await frappe.call({ method: `${SP_TASK_API}.mark_done`, args: { task: frm.doc.name, ...values }, freeze: true });
					frm.reload_doc();
				},
				__("Mark Done")
			);
		});
	},
});

function sp_task_check_in(frm) {
	const send = async (position) => {
		const args = { task: frm.doc.name };
		if (position) Object.assign(args, { lat: position.coords.latitude, lng: position.coords.longitude });
		await frappe.call({ method: `${SP_TASK_API}.check_in`, args, freeze: true });
		frm.reload_doc();
	};
	if (!navigator.geolocation) return send(null);
	navigator.geolocation.getCurrentPosition(send, () => send(null), { timeout: 8000 }); // sp-allow-number: 8 s for a GPS fix
}
