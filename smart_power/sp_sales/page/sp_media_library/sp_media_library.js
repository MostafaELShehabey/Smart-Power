// MK3 Media library (SP-53): finished-station photos and videos that installations tagged usable
// for marketing, filtered by system type, region and kW. Each can be downloaded, and "Ask for more
// photos" gives installations a task on that station. No customer data is shown: the station no.,
// region, systems and kW only. The rules are on the server (smart_power.sp_sales.media).
const SP_ML_API = "smart_power.sp_sales.media";

frappe.pages["sp-media-library"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Media Library"), single_column: true });
	wrapper.sp_media = new SPMediaLibrary(page);
};

class SPMediaLibrary {
	constructor(page) {
		this.page = page;
		this.$main = $('<div class="sp-media-library"></div>').appendTo(page.main);
		this.$count = $('<div class="text-muted small mb-3"></div>').appendTo(this.$main);
		this.$grid = $('<div class="d-flex flex-wrap"></div>').appendTo(this.$main);
		this.$more = $('<div class="text-center my-3"></div>').appendTo(this.$main);
		this.make_filters();
	}

	async make_filters() {
		const { message: choices } = await frappe.call(`${SP_ML_API}.filters`);
		const select = (fieldname, label, all, rows) =>
			this.page.add_field({
				fieldname,
				label,
				fieldtype: "Select",
				options: [{ value: "", label: all }, ...rows],
				change: () => this.refresh(),
			});
		this.filters = {
			system_type: select("system_type", __("System Type"), __("All system types"), choices.system_types),
			region: select("region", __("Region"), __("All regions"), choices.regions),
			kw_from: this.page.add_field({
				fieldname: "kw_from",
				label: __("kW from"),
				fieldtype: "Float",
				change: () => this.refresh(),
			}),
			kw_to: this.page.add_field({
				fieldname: "kw_to",
				label: __("kW to"),
				fieldtype: "Float",
				change: () => this.refresh(),
			}),
		};
		this.refresh();
	}

	args() {
		const out = {};
		Object.entries(this.filters).forEach(([k, f]) => {
			const v = f.get_value();
			if (v !== "" && v !== null && v !== undefined && !(k.startsWith("kw") && !v)) out[k] = v;
		});
		return out;
	}

	async refresh() {
		this.shown = 0;
		this.$grid.empty();
		await this.load();
	}

	async load() {
		const { message } = await frappe.call(`${SP_ML_API}.library`, { ...this.args(), start: this.shown });
		this.shown += message.photos.length;
		message.photos.forEach((p) => this.card(p));
		this.$count.text(__("{0} of {1} photos", [this.shown, message.total]));
		this.$more.empty();
		if (!message.total) {
			this.$grid.html(
				`<div class="text-muted">${frappe.utils.escape_html(__("No photos match. Installations tag them on the site log or the station."))}</div>`
			);
		} else if (this.shown < message.total) {
			$('<button class="btn btn-default btn-sm"></button>')
				.text(__("Load more"))
				.on("click", () => this.load())
				.appendTo(this.$more);
		}
	}

	card(p) {
		const src = `/api/method/${SP_ML_API}.file?name=${encodeURIComponent(p.file)}`;
		const $card = $(`<div class="mr-3 mb-4 sp-media-card" style="width: 220px;">
			<a target="_blank" rel="noopener"></a>
			<div class="small mt-2"><b></b> <span class="text-muted sp-media-meta"></span></div>
			<div class="small text-muted sp-media-date"></div>
			<div class="mt-2 d-flex">
				<a class="btn btn-default btn-xs mr-2 sp-media-download"></a>
				<button class="btn btn-default btn-xs sp-media-ask"></button>
			</div>
		</div>`).appendTo(this.$grid);
		const $media = $(p.video ? "<video controls muted preload='metadata'></video>" : "<img loading='lazy'>")
			.addClass("rounded border")
			.css({ width: "220px", height: "160px", "object-fit": "cover" })
			.attr("src", src);
		$card.children("a").first().attr("href", src).append($media);
		$card.find("b").text(p.station);
		const meta = [p.region, p.systems.join(", "), p.kw ? `${format_number(p.kw, null, p.kw % 1 ? 1 : 0)} ${__("kW")}` : ""].filter(Boolean);
		$card.find(".sp-media-meta").text(meta.join(" · "));
		$card.find(".sp-media-date").text(frappe.datetime.str_to_user(p.date));
		$card.find(".sp-media-download").attr("href", `${src}&download=1`).text(__("Download"));
		$card
			.find(".sp-media-ask")
			.text(__("Ask for more photos"))
			.attr("title", __("A task for installations on station {0}", [p.station]))
			.on("click", () => this.ask(p.station));
	}

	ask(station) {
		frappe.prompt(
			{ fieldname: "note", fieldtype: "Small Text", label: __("What photos do you need?") },
			async ({ note }) => {
				const { message: asked } = await frappe.call({
					method: `${SP_ML_API}.request_photos`,
					args: { station, note },
				});
				frappe.show_alert({
					message: asked
						? __("Installations asked for more photos of {0}.", [station])
						: __("More photos of {0} are already asked for.", [station]),
					indicator: asked ? "green" : "orange",
				});
			},
			__("Ask for more photos of {0}", [station]),
			__("Ask")
		);
	}
}
