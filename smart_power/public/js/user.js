// User (SP-26): on your own profile, your own transit and custody balances (G6), never an
// official account's. The admin ticks "Create Transit / Custody Account" to make a person's account.
frappe.ui.form.on("User", {
	async refresh(frm) {
		if (frm.is_new() || frm.doc.name !== frappe.session.user) return;
		const { message: rows } = await frappe.call("smart_power.sp_finance.accounts.my_balances");
		if (!rows || !rows.length) return;
		const esc = frappe.utils.escape_html;
		// SP-116: cash held past the limit shows red until it is deposited
		const over = rows.some((r) => r.over);
		frm.dashboard.set_headline(
			rows
				.map((r) => {
					const held = r.days_held ? ` · ${esc(__("{0} days", [r.days_held]))}` : "";
					return `${esc(__(r.sp_account_kind === "Custody" ? "My custody" : "My cash"))}: <b>${esc(
						format_currency(r.balance, r.account_currency)
					)}</b> (${esc(r.account_name)}${held})`;
				})
				.join(" · ") + (over ? ` — <b>${esc(__("Deposit it into an official account."))}</b>` : ""),
			over ? "red" : "blue"
		);
	},
});
