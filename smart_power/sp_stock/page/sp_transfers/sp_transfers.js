// I4 Transfer orders (SP-88): purchasing creates them and the store or showroom issues them with a
// transfer note. The site confirms on Receive Goods. No price reaches this page. The rules are on
// the server (smart_power.sp_stock.transfers).
const SP_TR_API = "smart_power.sp_stock.transfers";
const SP_TR_COLORS = { Created: "orange", Issued: "blue", Received: "green", Discrepancy: "red", Cancelled: "gray" };

frappe.pages["sp-transfers"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Transfers"), single_column: true });
	wrapper.sp_transfers = new SPTransfers(page);
};

frappe.pages["sp-transfers"].on_page_show = function (wrapper) {
	wrapper.sp_transfers?.refresh();
};

class SPTransfers {
	constructor(page) {
		this.page = page;
		this.$main = $('<div class="sp-transfers"></div>').appendTo(page.main);
		page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
	}

	async refresh() {
		const { message } = await frappe.call(`${SP_TR_API}.my_transfers`);
		if (message.can_create) this.page.set_primary_action(__("New Transfer"), () => this.create(), "add");
		this.$main.empty();
		if (!message.transfers.length) {
			$(`<p class="text-muted mt-3">${frappe.utils.escape_html(__("No transfer orders yet."))}</p>`).appendTo(this.$main);
		}
		message.transfers.forEach((transfer) => this.render_card(transfer, message.can_create));
	}

	render_card(transfer, can_create) {
		const esc = frappe.utils.escape_html;
		const lines = transfer.lines
			.map(
				(l) => `<tr><td>${esc(l.item_name || l.item_code)}<div class="small text-muted">${esc(l.item_code)}</div></td>
					<td class="text-nowrap text-right">${esc(String(l.qty))} ${esc(__(l.uom || ""))}</td></tr>`
			)
			.join("");
		const note = transfer.issue_entry
			? `<a class="btn btn-default btn-sm" target="_blank" rel="noopener" href="/printview?doctype=${encodeURIComponent("Stock Entry")}&name=${encodeURIComponent(transfer.issue_entry)}&format=${encodeURIComponent("SP Transfer Note")}&no_letterhead=1">${esc(__("Print Transfer Note"))}</a>`
			: "";
		const $card = $(`<div class="frappe-card p-3 mb-3 sp-transfer-card">
			<div class="d-flex flex-wrap justify-content-between align-items-start mb-2" style="gap: 8px">
				<div>
					<b>${esc(transfer.name)}</b>
					<span class="indicator-pill ${SP_TR_COLORS[transfer.status] || "gray"}">${esc(__(transfer.status))}</span>
					<div class="small text-muted">${esc(transfer.source)} → ${esc(transfer.site)} · ${esc(transfer.station)}</div>
					<div class="small text-muted">${esc(__(transfer.transport || ""))} · ${esc(frappe.datetime.str_to_user(transfer.schedule_date))}</div>
				</div>
				<div class="d-flex flex-wrap" style="gap: 8px">
					${note}
					${can_create && transfer.status === "Created" ? `<button class="btn btn-default btn-sm sp-tr-cancel">${esc(__("Cancel"))}</button>` : ""}
					${transfer.can_issue ? `<button class="btn btn-primary btn-sm sp-tr-issue">${esc(__("Issue"))}</button>` : ""}
				</div>
			</div>
			<div class="table-responsive"><table class="table table-sm mb-0"><tbody>${lines}</tbody></table></div>
		</div>`).appendTo(this.$main);
		$card.find(".sp-tr-issue").on("click", () => this.issue(transfer));
		$card.find(".sp-tr-cancel").on("click", () => {
			frappe.confirm(__("Cancel transfer {0}?", [transfer.name]), () => this.act("cancel_transfer", { name: transfer.name }));
		});
	}

	async act(method, args) {
		const { message } = await frappe.call({ method: `${SP_TR_API}.${method}`, args, freeze: true });
		this.refresh();
		return message;
	}

	issue(transfer) {
		const serial = transfer.lines.filter((l) => l.serial);
		if (!serial.length) {
			frappe.confirm(__("Issue transfer {0}? The stock leaves {1}.", [transfer.name, transfer.source]), () => this.send(transfer, {}));
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: __("Issue {0}", [transfer.name]),
			fields: serial.map((l) => ({
				fieldname: l.name,
				fieldtype: "Small Text",
				label: __("Serial numbers of {0} ({1})", [l.item_name || l.item_code, l.qty]),
				description: __("One serial number on each line."),
				reqd: 1,
			})),
			primary_action_label: __("Issue"),
			primary_action: (values) => {
				dialog.hide();
				this.send(transfer, values);
			},
		});
		dialog.show();
	}

	async send(transfer, serials) {
		const entry = await this.act("issue_transfer", { name: transfer.name, serials });
		frappe.show_alert({ message: __("Transfer {0} issued in {1}", [transfer.name, entry]), indicator: "green" });
	}

	create() {
		const dialog = new frappe.ui.Dialog({
			title: __("New Transfer"),
			size: "large",
			fields: [
				{ fieldname: "station", fieldtype: "Link", options: "SP Station", label: __("Station"), reqd: 1 },
				{
					fieldname: "source_kind",
					fieldtype: "Select",
					label: __("Transfer From"),
					reqd: 1,
					default: "Main",
					options: [
						{ value: "Main", label: __("Main Store") },
						{ value: "Showroom", label: __("Showroom (at cost)") },
					],
				},
				{ fieldname: "column", fieldtype: "Column Break" },
				{
					fieldname: "transport",
					fieldtype: "Select",
					label: __("Transport"),
					reqd: 1,
					default: "Jumbo",
					options: [
						{ value: "Jumbo", label: __("Jumbo") },
						{ value: "Winch", label: __("Winch") },
						{ value: "Other", label: __("Other") },
					],
				},
				{ fieldname: "planned_date", fieldtype: "Date", label: __("Date"), reqd: 1, default: frappe.datetime.get_today() },
				{ fieldname: "section", fieldtype: "Section Break" },
				{
					fieldname: "items",
					fieldtype: "Table",
					label: __("Items"),
					reqd: 1,
					cannot_add_rows: false,
					in_place_edit: true,
					data: [],
					fields: [
						{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), in_list_view: 1, reqd: 1, columns: 7 }, // sp-allow-number: grid column width
						{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1, reqd: 1, columns: 3 }, // sp-allow-number: grid column width
					],
				},
			],
			primary_action_label: __("Create Transfer"),
			primary_action: async (values) => {
				const name = await this.act("create_transfer", { values });
				dialog.hide();
				frappe.show_alert({ message: __("Transfer {0} sent to the store", [name]), indicator: "green" });
			},
		});
		dialog.show();
	}
}
