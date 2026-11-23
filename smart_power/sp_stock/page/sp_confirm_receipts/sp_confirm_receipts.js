// P4 Receipt confirmation (SP-85): each waiting receipt against its order, with the exit permit and
// the receiver. No price reaches this page. The rules are on the server
// (smart_power.sp_stock.receipt_confirmation).
const SP_RC_API = "smart_power.sp_stock.receipt_confirmation";

frappe.pages["sp-confirm-receipts"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Confirm Receipts"), single_column: true });
	wrapper.sp_confirm = new SPConfirmReceipts(page);
};

frappe.pages["sp-confirm-receipts"].on_page_show = function (wrapper) {
	wrapper.sp_confirm?.refresh();
};

class SPConfirmReceipts {
	constructor(page) {
		this.page = page;
		this.$main = $('<div class="sp-confirm"></div>').appendTo(page.main);
		page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
	}

	async refresh() {
		const { message: receipts } = await frappe.call(`${SP_RC_API}.pending_receipts`);
		this.$main.empty();
		if (!receipts.length) {
			$(`<p class="text-muted mt-3">${frappe.utils.escape_html(__("No receipts are waiting for confirmation."))}</p>`).appendTo(this.$main);
		}
		receipts.forEach((receipt) => this.render_card(receipt));
	}

	line_row(line) {
		const esc = frappe.utils.escape_html;
		const color = line.condition === "OK" ? "green" : line.condition === "Damaged" ? "red" : "orange";
		const serial = line.serial_no
			? `<div class="small">${esc(line.serial_no)}${
					line.serial_photo ? ` · <a href="${esc(line.serial_photo)}" target="_blank" rel="noopener">${esc(__("Nameplate Photo"))}</a>` : ""
			  }</div>`
			: "";
		return `<tr>
			<td>${esc(line.item_name || line.item_code)}<div class="small text-muted">${esc(line.item_code)}</div>${serial}</td>
			<td class="text-nowrap">${esc(String(line.ordered))} ${esc(__(line.uom || ""))}</td>
			<td class="text-nowrap">${esc(String(line.already_received))}</td>
			<td class="text-nowrap"><b>${esc(String(line.received_qty))}</b></td>
			<td><span class="indicator-pill ${color}">${esc(__(line.condition))}</span></td>
			<td>${esc(line.note || "")}</td>
		</tr>`;
	}

	weight_note(weight) {
		// iron (SP-178): the scale weight against the order's theoretical weight, red above the limit
		if (!weight) return "";
		const esc = frappe.utils.escape_html;
		const text = __("Scale weight {0} kg against a theoretical {1} kg", [weight.actual_kg, weight.theoretical_kg]);
		const pct = `${weight.variance_pct > 0 ? "+" : ""}${weight.variance_pct}%`;
		return `<div class="small mb-2 sp-confirm-weight ${weight.warning ? "text-danger" : "text-muted"}">${esc(text)} · <span dir="ltr">${esc(pct)}</span>${
			weight.warning ? ` · <b>${esc(weight.warning)}</b>` : ""
		}</div>`;
	}

	render_card(receipt) {
		const esc = frappe.utils.escape_html;
		const all_ok = receipt.lines.every((line) => line.condition === "OK");
		const $card = $(`<div class="frappe-card p-3 mb-3 sp-confirm-card">
			<div class="d-flex flex-wrap justify-content-between align-items-start mb-2" style="gap: 8px">
				<div>
					<b>${esc(receipt.supplier_name || receipt.purchase_order)}</b>
					<div class="small text-muted">
						<a href="/app/purchase-receipt/${encodeURIComponent(receipt.name)}">${esc(receipt.name)}</a>
						· ${esc(receipt.purchase_order)} · ${esc(receipt.warehouse || "")}
					</div>
					<div class="small text-muted">${esc(__("Received by {0} on {1}", [receipt.received_by_name, frappe.datetime.str_to_user(receipt.posting_date)]))}</div>
				</div>
				<div class="d-flex flex-wrap" style="gap: 8px">
					<button class="btn btn-default btn-sm sp-confirm-reject">${esc(__("Reject"))}</button>
					<button class="btn btn-${all_ok ? "default" : "primary"} btn-sm sp-confirm-discrepancy">${esc(__("Mark Discrepancy"))}</button>
					${all_ok ? `<button class="btn btn-primary btn-sm sp-confirm-ok">${esc(__("Confirm"))}</button>` : ""}
				</div>
			</div>
			<div class="table-responsive"><table class="table table-sm mb-2">
				<thead><tr>
					<th>${esc(__("Item"))}</th><th>${esc(__("Ordered"))}</th><th>${esc(__("Already Received"))}</th>
					<th>${esc(__("Received"))}</th><th>${esc(__("Condition"))}</th><th>${esc(__("Note"))}</th>
				</tr></thead>
				<tbody>${receipt.lines.map((line) => this.line_row(line)).join("")}</tbody>
			</table></div>
			${this.weight_note(receipt.weight)}
			<div class="d-flex flex-wrap align-items-center" style="gap: 16px">
				<a href="${esc(receipt.exit_permit || "")}" target="_blank" rel="noopener" class="sp-confirm-permit">${esc(__("Exit Permit Photo"))}</a>
				${receipt.signature ? `<img src="${esc(receipt.signature)}" alt="${esc(__("Receiver Signature"))}" style="max-height: 48px">` : ""}
			</div>
		</div>`).appendTo(this.$main);
		$card.find(".sp-confirm-ok").on("click", () => this.confirm(receipt));
		$card.find(".sp-confirm-discrepancy").on("click", () => this.ask(receipt, "mark_discrepancy"));
		$card.find(".sp-confirm-reject").on("click", () => this.ask(receipt, "reject_receipt"));
	}

	confirm(receipt) {
		frappe.confirm(__("Confirm {0}? Stock and the supplier's payable will post.", [receipt.name]), () =>
			this.act("confirm_receipt", { receipt: receipt.name }, __("Receipt {0} confirmed", [receipt.name]))
		);
	}

	ask(receipt, method) {
		const rejecting = method === "reject_receipt";
		const field = rejecting ? "reason" : "notes";
		const dialog = new frappe.ui.Dialog({
			title: rejecting ? __("Reject {0}", [receipt.name]) : __("Mark Discrepancy on {0}", [receipt.name]),
			fields: [
				{
					fieldname: "help",
					fieldtype: "HTML",
					options: `<p class="text-muted small">${frappe.utils.escape_html(
						rejecting
							? __("Nothing posts. The receiver gets a task with your reason.")
							: __("The good quantity posts. The damaged quantity stays open on the order.")
					)}</p>`,
				},
				{ fieldname: field, fieldtype: "Small Text", label: rejecting ? __("Reason") : __("Notes"), reqd: 1 },
			],
			primary_action_label: rejecting ? __("Reject") : __("Mark Discrepancy"),
			primary_action: async (values) => {
				dialog.hide();
				await this.act(method, { receipt: receipt.name, [field]: values[field] }, __("Receipt {0} updated", [receipt.name]));
			},
		});
		dialog.show();
	}

	async act(method, args, done) {
		await frappe.call({ method: `${SP_RC_API}.${method}`, args, freeze: true });
		frappe.show_alert({ message: done, indicator: "green" });
		this.refresh();
	}
}
