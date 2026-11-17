// SL1 site daily log (SP-96): the crew's wage comes from the worker, the materials show what the
// site holds, and each photo can be tagged usable for marketing (SP-53).
const SP_SL_API = "smart_power.sp_site.site_log";

frappe.ui.form.on("SP Site Daily Log", {
	setup(frm) {
		// cancelling reverses its own stock entry and labour entry
		frm.ignore_doctypes_on_cancel_all = ["Stock Entry", "Journal Entry"];
		frm.set_query("paid_from", () => ({
			filters: { sp_account_kind: "Custody", is_group: 0, company: frm.doc.company },
		}));
	},
	refresh(frm) {
		smart_power.site_photos(frm, "photos_html", __("Save the log, then attach its photos."));
		if (frm.doc.docstatus === 1 && frm.doc.station) {
			frm.add_custom_button(__("Station cost"), async () => {
				const { message: cost } = await frappe.call(`${SP_SL_API}.station_cost`, { station: frm.doc.station });
				const esc = frappe.utils.escape_html;
				const rows = Object.entries(cost)
					.filter(([k]) => k !== "total")
					.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="text-right">${esc(format_currency(v))}</td></tr>`)
					.join("");
				frappe.msgprint({
					title: __("Actual cost of {0}", [frm.doc.station]),
					message: `<table class="table table-sm">${rows}<tr><th>${esc(__("Total"))}</th><th class="text-right">${esc(
						format_currency(cost.total)
					)}</th></tr></table>`,
				});
			});
		}
	},
});

frappe.ui.form.on("SP Crew Line", {
	async employee(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.employee) return;
		const { message } = await frappe.db.get_value("Employee", row.employee, "sp_daily_wage");
		await frappe.model.set_value(cdt, cdn, "wage", message.sp_daily_wage || 0);
	},
	days: (frm, cdt, cdn) => sp_crew_amount(frm, cdt, cdn),
	wage: (frm, cdt, cdn) => sp_crew_amount(frm, cdt, cdn),
});

function sp_crew_amount(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.days) * flt(row.wage));
	frm.set_value("labour_total", (frm.doc.crew || []).reduce((s, r) => s + flt(r.amount), 0));
}
