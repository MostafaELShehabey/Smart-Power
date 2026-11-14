// Document template (SP-134, X8): the placeholders of this document, Publish / New Version,
// and a preview filled from a real document. The rules are on the server.

frappe.ui.form.on("SP Document Template", {
	refresh(frm) {
		sp_doc_placeholders(frm);
		if (frm.is_new()) return;
		if (frm.doc.is_published) {
			frm.set_intro(__("Published: this version cannot change. Make a new version to edit."), "blue");
			frm.disable_form();
			frm.add_custom_button(__("Unpublish"), () => frm.call("unpublish").then(() => frm.reload_doc()));
		} else {
			frm.add_custom_button(__("Publish"), () =>
				frappe.confirm(
					__("Publish version {0}? New prints of this document use it.", [frm.doc.version]),
					() => frm.call("publish").then(() => frm.reload_doc())
				)
			);
		}
		frm.add_custom_button(__("New Version"), () =>
			frm.call("new_version").then((r) => frappe.set_route("Form", "SP Document Template", r.message))
		);
		frm.add_custom_button(__("Preview"), () => sp_doc_preview(frm));
	},
	document(frm) {
		sp_doc_placeholders(frm);
	},
});

function sp_doc_placeholders(frm) {
	const list = (frm.doc.__onload && frm.doc.__onload.placeholders) || [];
	const esc = frappe.utils.escape_html;
	const chips = list.map((p) => `<code class="mr-2">{${esc(p)}}</code>`).join("");
	frm.get_field("placeholders_html").$wrapper.html(
		list.length
			? `<div class="text-muted small mb-1">${esc(__("Placeholders you can use"))}</div><div>${chips}</div>`
			: `<div class="text-muted small">${esc(__("Save to see the placeholders of this document."))}</div>`
	);
}

function sp_doc_preview(frm) {
	const doctypes = { Quotation: "Quotation", Contract: "Sales Order", Invoice: "Sales Invoice" };
	const doctype = doctypes[frm.doc.document];
	const show = async (reference) => {
		const { message: blocks } = await frm.call("preview", { reference: reference || null });
		frappe.msgprint({
			title: __("Preview"),
			wide: true,
			message: `<div dir="rtl" class="sp-print">${blocks.join("")}</div>`,
		});
	};
	if (!doctype) return show(null);
	frappe.prompt(
		{
			fieldname: "reference",
			fieldtype: "Link",
			options: doctype,
			label: __("Fill from"),
			description: __("Empty shows the placeholders as they are."),
		},
		(values) => show(values.reference),
		__("Preview"),
		__("Show")
	);
}
