// X9 Automations (SP-135): "Test" runs the automation on one record without doing anything.
frappe.ui.form.on("SP Automation", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Test on a Record"), () => {
			frappe.prompt(
				{ fieldname: "record", fieldtype: "Link", options: frm.doc.doctype_name, label: __("Record"), reqd: 1 },
				async ({ record }) => {
					const { message: r } = await frappe.call("smart_power.sp_core.automation.test", { name: frm.doc.name, docname: record });
					const esc = frappe.utils.escape_html;
					const conds = r.conditions.map((c) => `<li>${c.ok ? "✓" : "✗"} ${esc(c.field)} ${esc(__(c.op))} ${esc(c.value || "")} (${__("now")}: ${esc(c.actual)})</li>`).join("");
					const acts = r.actions.map((a) => `<li><b>${esc(__(a.kind))}</b> → ${a.users.map(esc).join("، ") || __("nobody")}: ${esc(a.subject)}</li>`).join("");
					frappe.msgprint({
						title: r.matches ? __("It would do this") : __("The conditions do not hold"),
						message: `${r.active ? "" : `<p>${__("The automation is paused: it does nothing now.")}</p>`}<ul>${conds}</ul>${acts ? `<ul>${acts}</ul>` : ""}<p class="text-muted">${__("Nothing was done: this was a test.")}</p>`,
					});
				},
				__("Test on a Record")
			);
		});
	},
	doctype_name(frm) {
		frm.set_value("watch_field", "");
	},
});
