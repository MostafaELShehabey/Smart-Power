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
		const [{ message: cards }, { message: receipts }, { message: transfers }] = await Promise.all([
			frappe.call(`${SP_GR_API}.expected_deliveries`),
			frappe.call(`${SP_GR_API}.my_receipts`),
			frappe.call("smart_power.sp_stock.transfers.transfers_to_confirm"),
		]);
		this.render(cards, receipts, transfers);
	}

	render(cards, receipts, transfers) {
		const esc = frappe.utils.escape_html;
		this.$main.empty();
		if (transfers.length) {
			$(`<h5 class="mt-3">${esc(__("Transfers to Confirm"))}</h5>`).appendTo(this.$main);
			transfers.forEach((transfer) => this.render_transfer(transfer));
		}
		$(`<h5 class="mt-3">${esc(__("Expected Deliveries"))}</h5>`).appendTo(this.$main);
		if (!cards.length) {
			$(`<p class="text-muted">${esc(__("No deliveries are expected at your destinations."))}</p>`).appendTo(this.$main);
		}
		cards.forEach((card) => this.render_card(card));
		if (receipts.length) this.render_receipts(receipts);
	}

	// P3 in transfer mode (SP-88): what the store sent, counted on arrival
	render_transfer(transfer) {
		const esc = frappe.utils.escape_html;
		const rows = transfer.lines
			.map(
				(l) => `<tr class="sp-tr-line" data-row="${esc(l.row)}" data-left="${esc(String(l.left))}">
					<td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(l.item_code)}</div>
						${l.serial_no ? `<div class="small text-muted">${esc(l.serial_no.split("\n").join(", "))}</div>` : ""}</td>
					<td class="text-nowrap">${esc(String(l.left))} ${esc(__(l.uom || ""))}</td>
					<td style="max-width: 120px"><input type="number" min="0" max="${esc(String(l.left))}" class="form-control input-sm sp-tr-qty" value="${esc(String(l.left))}"></td>
				</tr>`
			)
			.join("");
		const $card = $(`<div class="frappe-card p-3 mb-3 sp-transfer-card">
			<div class="d-flex flex-wrap justify-content-between align-items-center mb-2" style="gap: 8px">
				<div><b>${esc(transfer.name)}</b><div class="small text-muted">${esc(transfer.source)} · ${esc(transfer.station)}</div></div>
				<button class="btn btn-primary btn-sm sp-tr-confirm">${esc(__("Confirm Arrival"))}</button>
			</div>
			<div class="table-responsive"><table class="table table-sm mb-0">
				<thead><tr><th>${esc(__("Item"))}</th><th>${esc(__("In Transit"))}</th><th>${esc(__("Arrived"))}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table></div>
		</div>`).appendTo(this.$main);
		$card.find(".sp-tr-confirm").on("click", async () => {
			const lines = $card
				.find(".sp-tr-line")
				.map((_, el) => ({ row: el.dataset.row, qty: flt($(el).find(".sp-tr-qty").val()) }))
				.get();
			const { message } = await frappe.call({
				method: "smart_power.sp_stock.transfers.confirm_transfer",
				args: { name: transfer.name, lines },
				freeze: true,
			});
			frappe.show_alert({
				message: message.short ? __("{0} still in transit. Purchasing has been told.", [message.short]) : __("Transfer {0} received", [transfer.name]),
				indicator: message.short ? "orange" : "green",
			});
			this.refresh();
		});
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
					<td><a href="/app/purchase-receipt/${encodeURIComponent(r.name)}">${esc(r.name)}</a></td>
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

	// a serial-tracked item is recorded one unit per row, with its serial and nameplate photo
	serial_rows(line, index) {
		const esc = frappe.utils.escape_html;
		const units = Array.from({ length: Math.ceil(line.remaining) }, (_, unit) => unit);
		const rows = units
			.map(
				(unit) => `<tr class="sp-gr-unit" data-index="${index}">
					<td class="small text-muted">${unit + 1}</td>
					<td><input type="text" class="form-control input-sm sp-gr-serial" placeholder="${esc(__("Serial No"))}"></td>
					<td><select class="form-control input-sm sp-gr-condition">
						<option value="OK">${esc(__("OK"))}</option>
						<option value="Damaged">${esc(__("Damaged"))}</option>
					</select></td>
					<td class="text-nowrap">
						<button type="button" class="btn btn-default btn-xs sp-gr-photo">${esc(__("Nameplate Photo"))}</button>
						<span class="sp-gr-photo-ok text-success hidden">✓</span>
					</td>
				</tr>`
			)
			.join("");
		return `<div class="mb-3">
			<b>${esc(line.item_name || line.item_code)}</b>
			<div class="small text-muted mb-1">${esc(__("Still expected: {0}", [line.remaining]))}. ${esc(__("Leave a row empty if the unit did not arrive."))}</div>
			<div class="table-responsive"><table class="table table-sm"><tbody>${rows}</tbody></table></div>
		</div>`;
	}

	line_rows(card) {
		const esc = frappe.utils.escape_html;
		const plain = card.lines
			.map((l, i) => ({ l, i }))
			.filter(({ l }) => !l.serial)
			.map(
				({ l, i }) => `<tr class="sp-gr-line" data-index="${i}">
					<td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(__("Still expected: {0}", [l.remaining]))}</div></td>
					<td><input type="number" min="0" step="any" class="form-control input-sm sp-gr-good" value="${l.remaining}"></td>
					<td><input type="number" min="0" step="any" class="form-control input-sm sp-gr-damaged" value="0"></td>
					<td class="text-center"><input type="checkbox" class="sp-gr-short"></td>
					<td><input type="text" class="form-control input-sm sp-gr-note"></td>
				</tr>`
			)
			.join("");
		const table = plain
			? `<div class="table-responsive"><table class="table table-sm">
				<thead><tr><th>${esc(__("Item"))}</th><th>${esc(__("Good"))}</th><th>${esc(__("Damaged"))}</th><th>${esc(__("Short"))}</th><th>${esc(__("Note"))}</th></tr></thead>
				<tbody>${plain}</tbody>
			</table></div>`
			: "";
		const serials = card.lines
			.map((l, i) => (l.serial ? this.serial_rows(l, i) : ""))
			.join("");
		return table + serials;
	}

	bind_photos(dialog) {
		dialog.fields_dict.lines.$wrapper.on("click", ".sp-gr-photo", (e) => {
			const $row = $(e.currentTarget).closest("tr");
			new frappe.ui.FileUploader({
				allow_multiple: false,
				restrictions: { allowed_file_types: ["image/*"] },
				make_attachments_public: false,
				on_success: (file) => {
					$row.data("photo", file.file_url);
					$row.find(".sp-gr-photo-ok").removeClass("hidden");
				},
			});
		});
	}

	read_lines(dialog, card) {
		const lines = [];
		const $wrapper = dialog.fields_dict.lines.$wrapper;
		$wrapper.find(".sp-gr-line").each((_, tr) => {
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
		$wrapper.find(".sp-gr-unit").each((_, tr) => {
			const $tr = $(tr);
			const serial_no = ($tr.find(".sp-gr-serial").val() || "").trim();
			const serial_photo = $tr.data("photo");
			if (!serial_no && !serial_photo) return;
			lines.push({
				purchase_order_item: card.lines[$tr.data("index")].purchase_order_item,
				received_qty: 1,
				condition: $tr.find(".sp-gr-condition").val(),
				serial_no,
				serial_photo,
			});
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
		this.bind_photos(dialog);
		dialog.show();
	}
}
