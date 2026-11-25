// Crew salary (SP-181): a winch or Jumbo crew member's month, on the vehicle's center, with the
// advance installments taken off when advances are repaid by deduction.
// The rules are on the server (smart_power.sp_winch.crew_pay).

frappe.ui.form.on("SP Crew Salary", {
	setup(frm) {
		frm.set_query("paid_from", () => ({
			query: "smart_power.sp_finance.queries.account_picker",
			filters: { company: frm.doc.company },
		}));
		// the crew picker: the winch manager may not read HR's Employee list
		frm.set_query("employee", () => ({ query: "smart_power.sp_core.workers.worker_query" }));
	},
	async employee(frm) {
		frm.set_intro();
		if (!frm.doc.employee) return;
		const { message: start } = await frappe.call({
			method: "smart_power.sp_winch.crew_pay.salary_start",
			args: { employee: frm.doc.employee },
		});
		frm.set_value("employee_name", start.employee_name); // not fetched: HR's list is closed (BUG-10)
		if (start.monthly_salary) frm.set_value("gross_amount", start.monthly_salary);
		if (start.owed) {
			const note =
				start.mode === "Salary deduction" && !start.daily_worker
					? __("Still owes {0} on advances; this month's installment is deducted.", [
							format_currency(start.owed),
					  ])
					: __("Still owes {0} on advances, repaid in cash.", [format_currency(start.owed)]);
			frm.set_intro(note, "blue");
		}
	},
});
