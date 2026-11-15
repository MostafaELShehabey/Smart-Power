// Journal Entry (A6 / A6b, SP-119): a posted entry is never cancelled or amended; a manual one is
// reversed (Reverse), one made by a document is corrected through that document. While a manual
// entry is drafted, a live check shows whether it balances, and Submit waits until it does.
// The rules are on the server (smart_power.sp_finance.journal).

function sp_je_totals(frm) {
	let debit = 0;
	let credit = 0;
	(frm.doc.accounts || []).forEach((row) => {
		debit += flt(row.debit_in_account_currency);
		credit += flt(row.credit_in_account_currency);
	});
	const digits = precision("debit_in_account_currency", "Journal Entry Account");
	return { debit, credit, diff: flt(debit - credit, digits) };
}

function sp_je_balance_check(frm) {
	if (frm.doc.docstatus !== 0) return;
	const t = sp_je_totals(frm);
	const balanced = t.diff === 0 && t.debit > 0;
	frm.dashboard.clear_headline();
	frm.dashboard.set_headline(
		balanced
			? __("Balanced: debit {0} = credit {1}", [format_currency(t.debit), format_currency(t.credit)])
			: __("Not balanced: debit {0}, credit {1}, difference {2}", [ // sp-allow-number: placeholders
					format_currency(t.debit),
					format_currency(t.credit),
					format_currency(t.diff),
			  ]),
		balanced ? "green" : "red"
	);
	// a draft may be saved while it is typed; Submit waits until the entry balances
	if (!frm.is_new() && !frm.is_dirty()) frm.page.btn_primary.prop("disabled", !balanced);
}

frappe.ui.form.on("Journal Entry", {
	refresh(frm) {
		sp_je_balance_check(frm);
		if (frm.doc.docstatus !== 1) return;
		// never cancelled or amended by hand (the server refuses it too)
		frm.page.clear_secondary_action();
		if (frm.doc.sp_source_doctype && frm.doc.sp_source_name) {
			frm.set_intro(
				__("Posted by {0} {1}. Correct or cancel that document; its entry follows.", [
					__(frm.doc.sp_source_doctype),
					`<a href="/app/${frappe.router.slug(frm.doc.sp_source_doctype)}/${encodeURIComponent(frm.doc.sp_source_name)}">${frappe.utils.escape_html(frm.doc.sp_source_name)}</a>`,
				]),
				"blue"
			);
			return;
		}
		frm.add_custom_button(__("Reverse"), () =>
			frappe.confirm(__("Make a reversing entry of {0}?", [frm.doc.name]), async () => {
				const { message: name } = await frappe.call({
					method: "smart_power.sp_finance.journal.reverse",
					args: { name: frm.doc.name },
					freeze: true,
				});
				frappe.set_route("Form", "Journal Entry", name);
			})
		);
	},
});

frappe.ui.form.on("Journal Entry Account", {
	debit_in_account_currency: sp_je_balance_check,
	credit_in_account_currency: sp_je_balance_check,
	accounts_remove: sp_je_balance_check,
	accounts_add: sp_je_balance_check,
});
