// I5 Stock counts (SP-94): the store keeper counts a location on its sheet (typed or scanned), and the
// admin approves or rejects the differences. A blind sheet never receives the system quantity: the
// server leaves it out. The rules are on the server (smart_power.sp_stock.stock_count).
const SP_SC_API = "smart_power.sp_stock.stock_count";
const SP_SC_COLORS = { Draft: "orange", Submitted: "blue", Approved: "green", Rejected: "red" };

frappe.pages["sp-count-sheets"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Stock Counts"), single_column: true });
	wrapper.sp_counts = new SPCountSheets(page);
};

frappe.pages["sp-count-sheets"].on_page_show = function (wrapper) {
	wrapper.sp_counts?.show(frappe.get_route()[1]);
};

class SPCountSheets {
	constructor(page) {
		this.page = page;
		this.$main = $('<div class="sp-count-sheets"></div>').appendTo(page.main);
		page.set_secondary_action(__("Refresh"), () => this.show(frappe.get_route()[1]), "refresh");
	}

	show(name) {
		this.page.clear_primary_action();
		return name ? this.open_sheet(name) : this.refresh();
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_SC_API}.my_counts`);
		this.page.set_title(__("Stock Counts"));
		if (message.locations.length) this.page.set_primary_action(__("Start Count"), () => this.start(message.locations), "add");
		this.$main.empty();
		this.render_next(message.next);
		this.render_list(__("Open Count Sheets"), message.open, (row) => `<button class="btn btn-primary btn-sm sp-sc-open">${frappe.utils.escape_html(__("Open Sheet"))}</button>`);
		if (message.approver) this.render_decisions(message.to_decide);
		this.render_list(__("Recent Counts"), message.recent, (row) =>
			row.stock_reconciliation ? `<a class="small" href="/app/stock-reconciliation/${encodeURIComponent(row.stock_reconciliation)}">${frappe.utils.escape_html(row.stock_reconciliation)}</a>` : ""
		);
	}

	render_next(rows) {
		const esc = frappe.utils.escape_html;
		if (!rows.length) return;
		const today = frappe.datetime.get_today();
		const lines = rows
			.map(
				(r) => `<tr><td>${esc(r.warehouse)}</td><td>${esc(r.every === "Week" ? __("Weekly") : __("Monthly"))}</td>
					<td class="text-nowrap">${r.due <= today ? `<span class="indicator-pill orange">${esc(__("Due now"))}</span>` : esc(frappe.datetime.str_to_user(r.due))}</td></tr>`
			)
			.join("");
		$(`<h5 class="mt-3">${esc(__("Next Counts"))}</h5>
			<div class="frappe-card p-3 mb-3"><div class="table-responsive"><table class="table table-sm mb-0">
				<thead><tr><th>${esc(__("Stock Location"))}</th><th>${esc(__("Count Every"))}</th><th>${esc(__("Count Due"))}</th></tr></thead>
				<tbody>${lines}</tbody></table></div></div>`).appendTo(this.$main);
	}

	render_list(title, rows, actions) {
		const esc = frappe.utils.escape_html;
		$(`<h5 class="mt-3">${esc(title)}</h5>`).appendTo(this.$main);
		if (!rows.length) {
			$(`<p class="text-muted">${esc(__("None."))}</p>`).appendTo(this.$main);
			return;
		}
		rows.forEach((row) => {
			const $card = $(`<div class="frappe-card p-3 mb-2 sp-count-card">
				<div class="d-flex flex-wrap justify-content-between align-items-center" style="gap: 8px">
					<div><b>${esc(row.name)}</b>
						<span class="indicator-pill ${SP_SC_COLORS[row.status] || "gray"}">${esc(__(row.status))}</span>
						${row.blind ? `<span class="indicator-pill gray">${esc(__("Blind Count"))}</span>` : ""}
						<div class="small text-muted">${esc(row.warehouse)} · ${esc(frappe.datetime.str_to_user(row.count_date))}${row.differences ? ` · ${esc(__("{0} differences", [row.differences]))}` : ""}</div>
						${row.reason ? `<div class="small">${esc(row.reason)}</div>` : ""}
					</div>
					<div>${actions(row)}</div>
				</div>
			</div>`).appendTo(this.$main);
			$card.find(".sp-sc-open").on("click", () => frappe.set_route("sp-count-sheets", row.name));
		});
	}

	render_decisions(rows) {
		const esc = frappe.utils.escape_html;
		$(`<h5 class="mt-3">${esc(__("Count Differences"))}</h5>`).appendTo(this.$main);
		if (!rows.length) {
			$(`<p class="text-muted">${esc(__("No differences waiting."))}</p>`).appendTo(this.$main);
			return;
		}
		rows.forEach((row) => {
			const has_value = row.lines.some((l) => l.value !== undefined);
			const lines = row.lines
				.map(
					(l) => `<tr>
						<td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(l.item_code)}</div>${l.note ? `<div class="small">${esc(l.note)}</div>` : ""}</td>
						<td class="text-right">${esc(format_number(l.system_qty))}</td>
						<td class="text-right">${esc(format_number(l.counted_qty))}</td>
						<td class="text-right ${l.diff < 0 ? "text-danger" : "text-success"}">${esc(format_number(l.diff))} ${esc(__(l.uom || ""))}</td>
						${has_value ? `<td class="text-right">${esc(format_currency(l.value))}</td>` : ""}
					</tr>`
				)
				.join("");
			const $card = $(`<div class="frappe-card p-3 mb-3 sp-decision-card">
				<div class="d-flex flex-wrap justify-content-between align-items-start mb-2" style="gap: 8px">
					<div><b>${esc(row.name)}</b><div class="small text-muted">${esc(row.warehouse)} · ${esc(frappe.datetime.str_to_user(row.count_date))} · ${esc(frappe.user.full_name(row.counted_by))}</div></div>
					<div class="d-flex flex-wrap" style="gap: 8px">
						<button class="btn btn-default btn-sm sp-sc-reject">${esc(__("Reject"))}</button>
						<button class="btn btn-primary btn-sm sp-sc-approve">${esc(__("Approve"))}</button>
					</div>
				</div>
				<div class="table-responsive"><table class="table table-sm mb-0">
					<thead><tr><th>${esc(__("Item"))}</th><th class="text-right">${esc(__("System Qty"))}</th><th class="text-right">${esc(__("Counted Qty"))}</th><th class="text-right">${esc(__("Difference"))}</th>${has_value ? `<th class="text-right">${esc(__("Value"))}</th>` : ""}</tr></thead>
					<tbody>${lines}</tbody>
				</table></div>
			</div>`).appendTo(this.$main);
			$card.find(".sp-sc-approve").on("click", () => this.decide(row, "approve_count", __("Approve Count {0}", [row.name]), __("Approve")));
			$card.find(".sp-sc-reject").on("click", () => this.decide(row, "reject_count", __("Reject Count {0}", [row.name]), __("Reject")));
		});
	}

	decide(row, method, title, label) {
		const dialog = new frappe.ui.Dialog({
			title,
			fields: [{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
			primary_action_label: label,
			primary_action: async ({ reason }) => {
				const { message } = await frappe.call({ method: `${SP_SC_API}.${method}`, args: { name: row.name, reason }, freeze: true });
				dialog.hide();
				frappe.show_alert({
					message: message.stock_reconciliation
						? __("Count {0} approved: {1} posted", [row.name, message.stock_reconciliation])
						: message.recount
							? __("Count {0} rejected: {1} sent to be counted again", [row.name, message.recount])
							: __("Count {0} approved", [row.name]),
					indicator: message.recount ? "orange" : "green",
				});
				this.refresh();
			},
		});
		dialog.show();
	}

	start(locations) {
		const dialog = new frappe.ui.Dialog({
			title: __("Start Count"),
			fields: [
				{ fieldname: "warehouse", fieldtype: "Select", label: __("Stock Location"), reqd: 1, options: locations, default: locations[0] },
				{ fieldname: "blind", fieldtype: "Check", label: __("Blind Count"), default: 1, description: __("The store keeper does not see the system quantity until the count is submitted.") },
			],
			primary_action_label: __("Start Count"),
			primary_action: async (values) => {
				const { message: name } = await frappe.call({ method: `${SP_SC_API}.start_count`, args: values, freeze: true });
				dialog.hide();
				frappe.set_route("sp-count-sheets", name);
			},
		});
		dialog.show();
	}

	// ------------------------------------------------------------ the sheet

	async open_sheet(name) {
		const { message } = await frappe.call({ method: `${SP_SC_API}.sheet`, args: { name } });
		this.sheet = message;
		this.page.set_title(__("Count Sheet {0}", [message.name]));
		if (message.can_edit) this.page.set_primary_action(__("Submit Count"), () => this.submit(), "check");
		this.draw_sheet();
	}

	draw_sheet() {
		const esc = frappe.utils.escape_html;
		const s = this.sheet;
		const shows_system = s.lines.some((l) => l.system_qty !== undefined);
		this.$main.empty();
		$(`<div class="d-flex flex-wrap justify-content-between align-items-center mt-3 mb-2" style="gap: 8px">
			<div><b>${esc(s.warehouse)}</b> · ${esc(frappe.datetime.str_to_user(s.count_date))}
				<span class="indicator-pill ${SP_SC_COLORS[s.status] || "gray"}">${esc(__(s.status))}</span>
				${s.blind ? `<span class="indicator-pill gray">${esc(__("Blind Count"))}</span>` : ""}</div>
			<button class="btn btn-default btn-sm sp-sc-back">${esc(__("All Counts"))}</button>
		</div>`).appendTo(this.$main);
		this.$main.find(".sp-sc-back").on("click", () => frappe.set_route("sp-count-sheets"));
		if (s.reason) $(`<p class="small">${esc(__("Reason"))}: ${esc(s.reason)}</p>`).appendTo(this.$main);
		if (s.can_edit) {
			const $scan = $(`<div class="frappe-card p-3 mb-3">
				<label class="control-label">${esc(__("Scan a barcode or type an item code"))}</label>
				<input type="text" class="form-control sp-sc-scan" autocomplete="off" inputmode="text">
				<div class="small text-muted mt-1">${esc(__("Each scan adds one to the item's count."))}</div>
			</div>`).appendTo(this.$main);
			$scan.find(".sp-sc-scan").on("keydown", (e) => {
				if (e.key !== "Enter") return;
				e.preventDefault();
				this.scan(e.target.value);
				e.target.value = "";
			});
		}
		const rows = s.lines
			.map(
				(l, i) => `<tr class="sp-sc-line" data-item="${esc(l.item_code)}">
					<td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(l.item_code)} · ${esc(__(l.uom || ""))}</div></td>
					${shows_system ? `<td class="text-right">${esc(format_number(l.system_qty))}</td>` : ""}
					<td style="max-width: 110px">${
						s.can_edit
							? `<input type="number" min="0" step="any" class="form-control input-sm sp-sc-qty" value="${l.counted ? esc(String(l.counted_qty)) : ""}" data-index="${i}">`
							: esc(format_number(l.counted_qty))
					}</td>
					${s.status !== "Draft" && shows_system ? `<td class="text-right">${esc(format_number(l.diff))}</td>` : ""}
					<td>${s.can_edit ? `<input type="text" class="form-control input-sm sp-sc-note" value="${esc(l.note || "")}">` : esc(l.note || "")}</td>
				</tr>`
			)
			.join("");
		const counted = s.lines.filter((l) => l.counted).length;
		$(`<div class="frappe-card p-3 mb-3">
			<div class="small text-muted mb-2">${esc(__("{0} of {1} lines counted", [counted, s.lines.length]))}</div>
			<div class="table-responsive"><table class="table table-sm mb-0">
				<thead><tr><th>${esc(__("Item"))}</th>${shows_system ? `<th class="text-right">${esc(__("System Qty"))}</th>` : ""}<th>${esc(__("Counted Qty"))}</th>${
					s.status !== "Draft" && shows_system ? `<th class="text-right">${esc(__("Difference"))}</th>` : ""
				}<th>${esc(__("Note"))}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table></div>
			${s.can_edit ? `<button class="btn btn-default btn-sm mt-3 sp-sc-save">${esc(__("Save"))}</button>` : ""}
		</div>`).appendTo(this.$main);
		this.$main.find(".sp-sc-save").on("click", () => this.save());
		if (s.stock_reconciliation) {
			$(`<p><a href="/app/stock-reconciliation/${encodeURIComponent(s.stock_reconciliation)}">${esc(__("Stock Reconciliation"))} ${esc(s.stock_reconciliation)}</a></p>`).appendTo(this.$main);
		}
	}

	lines_from_screen() {
		return this.$main
			.find(".sp-sc-line")
			.map((_, el) => {
				const qty = $(el).find(".sp-sc-qty").val();
				return { item_code: el.dataset.item, counted_qty: qty === "" ? null : flt(qty), note: $(el).find(".sp-sc-note").val() };
			})
			.get();
	}

	async save(extra = []) {
		const { message } = await frappe.call({
			method: `${SP_SC_API}.save_counts`,
			args: { name: this.sheet.name, lines: [...this.lines_from_screen(), ...extra] },
			freeze: true,
		});
		this.sheet = message;
		this.draw_sheet();
	}

	async scan(code) {
		code = (code || "").trim();
		if (!code) return;
		const { message: item } = await frappe.call({ method: `${SP_SC_API}.find_item`, args: { code } });
		if (!item) {
			frappe.show_alert({ message: __("No item with barcode or code {0}", [code]), indicator: "red" });
			return;
		}
		const $line = this.$main.find(`.sp-sc-line[data-item="${CSS.escape(item.item_code)}"]`);
		if ($line.length) {
			const $qty = $line.find(".sp-sc-qty");
			$qty.val(flt($qty.val()) + 1);
			$line.addClass("table-active");
			setTimeout(() => $line.removeClass("table-active"), 600); // sp-allow-number: a short highlight (ms)
			this.$main.find(".sp-sc-scan").trigger("focus");
			return;
		}
		// found on the shelf but not on the sheet: it joins the sheet with one counted
		await this.save([{ item_code: item.item_code, counted_qty: 1 }]);
		frappe.show_alert({ message: __("{0} added to the sheet", [item.item_name || item.item_code]), indicator: "blue" });
		this.$main.find(".sp-sc-scan").trigger("focus");
	}

	submit() {
		frappe.confirm(__("Submit count {0}? The counted quantities can no longer be changed.", [this.sheet.name]), async () => {
			await this.save();
			const { message } = await frappe.call({ method: `${SP_SC_API}.submit_count`, args: { name: this.sheet.name }, freeze: true });
			frappe.show_alert({
				message: message.differences ? __("Count submitted: {0} differences sent to the admin", [message.differences]) : __("Count submitted: no differences"),
				indicator: message.differences ? "orange" : "green",
			});
			frappe.set_route("sp-count-sheets");
		});
	}
}
