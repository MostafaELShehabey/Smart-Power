// P3 Receive goods (SP-84): the deliveries expected at my destinations, and what arrived. No price
// ever reaches this page. The rules are on the server (smart_power.sp_stock.goods_receipt).
const SP_GR_API = "smart_power.sp_stock.goods_receipt";

frappe.pages["sp-receive-goods"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Receive Goods"), single_column: true });
	wrapper.sp_receive = new SPReceiveGoods(page);
};

frappe.pages["sp-receive-goods"].on_page_show = function (wrapper) {
	wrapper.sp_receive?.refresh();
};

class SPReceiveGoods {
	constructor(page) {
		this.page = page;
		this.$main = $('<div class="sp-receive"></div>').appendTo(page.main);
		page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
	}

	async refresh() {
		const [{ message: cards }, { message: receipts }] = await Promise.all([
			frappe.call(`${SP_GR_API}.expected_deliveries`),
			frappe.call(`${SP_GR_API}.my_receipts`),
		]);
		this.render(cards, receipts);
	}

	render(cards, receipts) {
		const esc = frappe.utils.escape_html;
		this.$main.empty();
		$(`<h5 class="mt-3">${esc(__("Expected Deliveries"))}</h5>`).appendTo(this.$main);
		if (!cards.length) {
			$(`<p class="text-muted">${esc(__("No deliveries are expected at your destinations."))}</p>`).appendTo(this.$main);
		}
		cards.forEach((card) => this.render_card(card));
		if (receipts.length) this.render_receipts(receipts);
	}

	render_card(card) {
		const esc = frappe.utils.escape_html;
		const lines = card.lines
			.map(
				(l) => `<tr>
					<td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(l.item_code)}</div></td>
					<td class="text-nowrap">${esc(l.due ? frappe.datetime.str_to_user(l.due) : "")}</td>
					<td class="text-nowrap">${esc(__("{0} (received {1})", [l.ordered, l.received]))} ${esc(__(l.uom || ""))}</td>
				</tr>`
			)
			.join("");
		const $card = $(`<div class="frappe-card p-3 mb-3 sp-receive-card">
			<div class="d-flex flex-wrap justify-content-between align-items-center mb-2" style="gap: 8px">
				<div>
					<b>${esc(card.supplier || card.purchase_order)}</b>
					<div class="small text-muted">${esc(card.purchase_order)} · ${esc(card.warehouse)}</div>
				</div>
				<button class="btn btn-primary btn-sm sp-receive-open">${esc(__("Receive"))}</button>
			</div>
			<div class="table-responsive"><table class="table table-sm mb-0">
				<thead><tr><th>${esc(__("Item"))}</th><th>${esc(__("Due"))}</th><th>${esc(__("Ordered"))}</th></tr></thead>
				<tbody>${lines}</tbody>
			</table></div>
		</div>`).appendTo(this.$main);
		$card.find(".sp-receive-open").on("click", () => this.receive(card));
	}

	render_receipts(receipts) {
		const esc = frappe.utils.escape_html;
		const colors = { "Pending confirmation": "orange", Confirmed: "green", Rejected: "red", Discrepancy: "orange" };
		const rows = receipts
			.map(
				(r) => `<tr>
					<td><a href="/app/sp-goods-receipt/${encodeURIComponent(r.name)}">${esc(r.name)}</a></td>
					<td>${esc(r.supplier_name || r.purchase_order)}</td>
					<td><span class="indicator-pill ${colors[r.status] || "gray"}">${esc(__(r.status))}</span></td>
					<td class="small">${esc(r.reject_reason || "")}</td>
				</tr>`
			)
			.join("");
		$(`<h5 class="mt-4">${esc(__("My Receipts"))}</h5>
			<div class="table-responsive"><table class="table table-sm bg-white">
				<thead><tr><th>${esc(__("Receipt"))}</th><th>${esc(__("Supplier"))}</th><th>${esc(__("Status"))}</th><th>${esc(__("Reject Reason"))}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table></div>`).appendTo(this.$main);
	}

	line_rows(card) {
		const esc = frappe.utils.escape_html;
		const rows = card.lines
			.map(
				(l, i) => `<tr data-index="${i}">
					<td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(__("Still expected: {0}", [l.remaining]))}</div></td>
					<td><input type="number" min="0" step="any" class="form-control input-sm sp-gr-good" value="${l.remaining}"></td>
					<td><input type="number" min="0" step="any" class="form-control input-sm sp-gr-damaged" value="0"></td>
					<td class="text-center"><input type="checkbox" class="sp-gr-short"></td>
					<td><input type="text" class="form-control input-sm sp-gr-note"></td>
				</tr>`
			)
			.join("");
		return `<div class="table-responsive"><table class="table table-sm">
			<thead><tr><th>${esc(__("Item"))}</th><th>${esc(__("Good"))}</th><th>${esc(__("Damaged"))}</th><th>${esc(__("Short"))}</th><th>${esc(__("Note"))}</th></tr></thead>
			<tbody>${rows}</tbody>
		</table></div>`;
	}

	read_lines(dialog, card) {
		const lines = [];
		dialog.fields_dict.lines.$wrapper.find("tbody tr").each((_, tr) => {
			const $tr = $(tr);
			const line = card.lines[$tr.data("index")];
			const note = $tr.find(".sp-gr-note").val();
			const good = flt($tr.find(".sp-gr-good").val());
			const damaged = flt($tr.find(".sp-gr-damaged").val());
			const base = { purchase_order_item: line.purchase_order_item, note };
			if (good > 0) {
				lines.push({ ...base, received_qty: good, condition: $tr.find(".sp-gr-short").prop("checked") ? "Short" : "OK" });
			}
			if (damaged > 0) lines.push({ ...base, received_qty: damaged, condition: "Damaged" });
		});
		return lines;
	}

	receive(card) {
		const dialog = new frappe.ui.Dialog({
			title: __("Receive {0}", [card.purchase_order]),
			size: "large",
			fields: [
				{ fieldname: "lines", fieldtype: "HTML", options: this.line_rows(card) },
				{ fieldname: "exit_permit_photo", fieldtype: "Attach Image", label: __("Exit Permit Photo"), reqd: 1 },
				{ fieldname: "signature", fieldtype: "Signature", label: __("Receiver Signature"), reqd: 1 },
			],
			primary_action_label: __("Save Receipt"),
			primary_action: async (values) => {
				const lines = this.read_lines(dialog, card);
				if (!lines.length) {
					frappe.msgprint(__("Enter what was received."));
					return;
				}
				const { message } = await frappe.call({
					method: `${SP_GR_API}.record_receipt`,
					args: {
						purchase_order: card.purchase_order,
						warehouse: card.warehouse,
						lines,
						exit_permit_photo: values.exit_permit_photo,
						signature: values.signature,
					},
					freeze: true,
				});
				dialog.hide();
				frappe.show_alert({ message: __("Receipt {0} is waiting for confirmation", [message.name]), indicator: "green" });
				this.refresh();
			},
		});
		dialog.show();
	}
}
