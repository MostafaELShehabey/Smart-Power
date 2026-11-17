// MK2 campaign record (SP-52): the funnel, "Record spend" from the agent's own custody (ERD 7.4:
// the spend counts once the admin approves her settlement), recount and close.
const SP_CMP_API = "smart_power.sp_sales.campaigns";

frappe.ui.form.on("SP Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;
		sp_campaign_funnel(frm);
		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("Record spend"), () => sp_campaign_spend(frm));
			frm.add_custom_button(__("Close campaign"), () =>
				frappe.confirm(__("Close this campaign? Its results stay."), async () => {
					await frappe.call({ method: `${SP_CMP_API}.close_campaign`, args: { campaign: frm.doc.name }, freeze: true });
					frm.reload_doc();
				})
			);
		}
		frm.add_custom_button(__("Recount"), async () => {
			await frappe.call({ method: `${SP_CMP_API}.recount`, args: { campaign: frm.doc.name }, freeze: true });
			frm.reload_doc();
		});
	},
});

function sp_campaign_funnel(frm) {
	const field = frm.fields_dict.funnel_html;
	const funnel = frm.doc.__onload && frm.doc.__onload.funnel;
	if (!field || !funnel) return;
	const $box = field.$wrapper.empty();
	const money = format_currency(frm.doc.contracted_value || 0);
	$(`<div class="text-muted small mb-2"></div>`)
		.text(__("Contracted value: {0} · Spend: {1}", [money, format_currency(frm.doc.spend_total || 0)]))
		.appendTo($box);
	const $chart = $("<div></div>").appendTo($box);
	new frappe.Chart($chart[0], {
		type: "bar",
		height: 220, // sp-allow-number: chart height in px
		data: { labels: funnel.map((s) => s.label), datasets: [{ values: funnel.map((s) => s.value) }] },
		colors: ["#c8a24a"],
	});
}

async function sp_campaign_spend(frm) {
	const { message: opts } = await frappe.call(`${SP_CMP_API}.spend_options`, { campaign: frm.doc.name });
	if (!opts.custodies.length) {
		frappe.msgprint(__("You have no open custody to spend from. Ask the admin to give you one."));
		return;
	}
	const choices = opts.custodies.map((c) => ({
		value: c.name,
		label: `${c.name} · ${format_currency(c.balance)}`,
	}));
	const d = new frappe.ui.Dialog({
		title: __("Record spend"),
		fields: [
			{ fieldname: "custody", fieldtype: "Select", label: __("Custody"), options: choices, default: choices[0].value, reqd: 1 },
			{ fieldname: "work_date", fieldtype: "Date", label: __("Date"), default: "Today", reqd: 1 },
			{ fieldname: "amount", fieldtype: "Currency", label: __("Amount"), reqd: 1 },
			{ fieldname: "receipt_photo", fieldtype: "Attach Image", label: __("Receipt") },
			{ fieldname: "note", fieldtype: "Small Text", label: __("Note") },
		],
		primary_action_label: __("Save"),
		primary_action: async (values) => {
			const custody = opts.custodies.find((c) => c.name === values.custody);
			await frappe.call({
				method: "smart_power.sp_finance.custody.add_expense",
				args: {
					custody: values.custody,
					values: {
						work_date: values.work_date,
						amount: values.amount,
						receipt_photo: values.receipt_photo,
						note: values.note,
						expense_type: opts.expense_type,
						center_type: "Center",
						cost_center: custody.cost_center,
						campaign: frm.doc.name,
					},
				},
				freeze: true,
			});
			d.hide();
			frappe.show_alert({
				message: __("Spend recorded. It counts once your custody settlement is approved."),
				indicator: "green",
			});
		},
	});
	d.show();
}
