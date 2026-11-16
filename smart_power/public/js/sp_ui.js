// Shared form components (SP-44). One library so every screen behaves the same way:
//   sp.ui.edit_with_reason(frm, fieldname)   change a saved number with a reason (History + RV2)
// The server side is smart_power.audit (the fields registered there get the button by themselves).
window.sp = window.sp || {};
sp.ui = sp.ui || {};

sp.ui.edit_with_reason = function (frm, fieldname) {
	const df = frappe.meta.get_docfield(frm.doctype, fieldname, frm.doc.name);
	const label = __(df.label);
	const d = new frappe.ui.Dialog({
		title: __("Change {0}", [label]),
		fields: [
			{ fieldname: "old", fieldtype: df.fieldtype, label: __("Now"), options: df.options, read_only: 1, default: frm.doc[fieldname] },
			{ fieldname: "value", fieldtype: df.fieldtype, label: __("New value"), options: df.options, reqd: 1 },
			{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1,
				description: __("It goes to the document's history and to the admin's review.") },
		],
		primary_action_label: __("Change"),
		primary_action: async (v) => {
			await frappe.xcall("smart_power.audit.edit_field", {
				doctype: frm.doctype, name: frm.doc.name, fieldname, value: v.value, reason: v.reason,
			});
			d.hide();
			frappe.show_alert({ message: __("{0} changed", [label]), indicator: "green" });
			frm.reload_doc();
		},
	});
	d.show();
};

// Every form whose doctype registers fields in smart_power.audit.EDITABLE gets a
// "Change … (with reason)" button for each field this user may change.
$(document).on("form-refresh", async (e, frm) => {
	if (!frm || frm.is_new() || !(frappe.boot.sp_editable || []).includes(frm.doctype)) return;
	const fields = await frappe.xcall("smart_power.audit.editable_fields", { doctype: frm.doctype, name: frm.doc.name });
	fields.forEach((f) =>
		frm.add_custom_button(
			__("Change {0} (with reason)", [__(frappe.meta.get_label(frm.doctype, f, frm.doc.name))]),
			() => sp.ui.edit_with_reason(frm, f)
		)
	);
});
