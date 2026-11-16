// SP-36: the admin gives the user a temporary password, to be changed at their next sign-in.
frappe.ui.form.on("SP Password Reset Request", {
	refresh(frm) {
		if (frm.doc.status !== "Open" || !frm.doc.user) return;
		frm.add_custom_button(__("Give a Temporary Password"), async () => {
			const password = await frappe.xcall("smart_power.sp_core.login.give_temporary_password", {
				request: frm.doc.name,
			});
			frappe.msgprint({
				title: __("Temporary Password"),
				indicator: "green",
				message: `${__("Give this password to {0}. They must change it when they sign in.", [
					frappe.utils.escape_html(frm.doc.full_name || frm.doc.user),
				])}<br><br><b style="font-size: 1.2em; user-select: all;">${frappe.utils.escape_html(password)}</b>`,
			});
			frm.reload_doc();
		}).addClass("btn-primary");
	},
});
