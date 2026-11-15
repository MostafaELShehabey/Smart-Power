// User (SP-26): on your own profile, your own transit and custody balances (G6), never an
// official account's. The admin ticks "Create Transit / Custody Account" to make a person's account.
frappe.ui.form.on("User", {
	async refresh(frm) {
		if (frm.is_new() || frm.doc.name !== frappe.session.user) return;
		const { message: rows } = await frappe.call("smart_power.sp_finance.accounts.my_balances");
		if (!rows || !rows.length) return;
		const esc = frappe.utils.escape_html;
		frm.dashboard.set_headline(
			rows
				.map(
					(r) =>
						`${esc(__(r.sp_account_kind === "Custody" ? "My custody" : "My cash"))}: <b>${esc(
							format_currency(r.balance, r.account_currency)
						)}</b> (${esc(r.account_name)})`
				)
				.join(" · ")
		);
	},
});
