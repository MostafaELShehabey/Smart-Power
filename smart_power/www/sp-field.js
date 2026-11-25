// The phone pages for light field entry (SP-180): Job, Expense and Money, saved online as the same
// SP Field Entry as the desk (SP-108). My entries show their lock (SP-109); a locked one can only be
// asked to reopen. Photos are shrunk and voice notes recorded small before they are uploaded.
// The rules are on the server (smart_power.sp_winch.field_page, field_entry, field_lock).

const SP_FP = "smart_power.sp_winch.field_page";
const SP_FE = "smart_power.sp_winch.field_entry";
const SP_FL = "smart_power.sp_winch.field_lock";
const SP_PHOTO_SIDE = 1600; // sp-allow-number: the longest side of an uploaded photo, in pixels
const SP_PHOTO_QUALITY = 0.7; // sp-allow-number: JPEG quality of an uploaded photo
const SP_VOICE_BITS = 24000; // sp-allow-number: bits per second of a recorded voice note
const SP_KIND_FIELDS = {
	Job: [
		"booking",
		"job_type",
		"for_kind",
		"station",
		"customer_name",
		"customer_phone",
		"internal_center",
		"place",
		"hp",
		"depth",
		"days",
		"hours",
		"km",
		"agreed_amount",
		"received_now",
		"received_method",
		"to_account",
	],
	Expense: ["expense_type", "paid_from", "odometer", "worker", "amount"],
	Money: ["money_kind", "related_job", "amount", "received_method", "to_account"],
};
const SP_COMMON_FIELDS = ["vehicle", "work_date", "on_behalf_of", "photo", "voice_note", "note"];
const SP_NUMBERS = ["hp", "depth", "days", "hours", "km", "agreed_amount", "received_now", "amount", "odometer"];

const sp_esc = (value) =>
	String(value === null || value === undefined ? "" : value).replace(
		/[&<>"']/g,
		(c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
	);

$(() => {
	const $page = $(".sp-field-page");
	if (!$page.length || !$page.find(".sp-entry-form").length) return;
	new SPFieldPage($page);
});

class SPFieldPage {
	constructor($page) {
		this.$page = $page;
		this.$form = $page.find(".sp-entry-form");
		this.t = window.sp_field_messages || {};
		this.kind = "Job";
		this.editing = null;
		this.bind();
		this.load();
	}

	field(name) {
		return this.$form.find(`[name="${name}"]`);
	}

	async load() {
		const { message } = await frappe.call({ method: `${SP_FP}.options` });
		this.options = message;
		this.fill_selects();
		this.reset();
		this.load_entries();
	}

	fill(name, rows, value = (r) => r.name, label = (r) => r.label || r.name, blank = true) {
		const esc = sp_esc;
		const $select = this.field(name).empty();
		if (blank) $select.append(`<option value="">${esc(this.t.choose || "")}</option>`);
		rows.forEach((r) => $select.append(`<option value="${esc(value(r))}">${esc(label(r))}</option>`));
	}

	fill_selects() {
		const o = this.options;
		this.fill("vehicle", o.vehicles, (r) => r.name, (r) => r.name, false);
		this.fill("job_type", o.job_types);
		this.fill("expense_type", o.expense_types);
		this.fill("received_method", o.methods);
		this.fill("station", o.stations, (r) => r.name, (r) => [r.name, r.customer_name].filter(Boolean).join(" · "));
		this.fill("internal_center", o.centers.map((c) => ({ name: c })));
		this.fill("to_account", o.accounts.map((a) => ({ name: a })));
		this.fill("worker", o.workers, (r) => r.name, (r) => r.employee_name || r.name);
		this.fill_open_jobs();
		if (o.operators.length) {
			this.$form.find(".sp-for-manager").removeClass("d-none");
			this.fill("on_behalf_of", o.operators, (r) => r.name, (r) => r.full_name || r.name);
		}
	}

	fill_open_jobs() {
		const jobs = this.options.open_jobs;
		this.fill(
			"related_job",
			jobs,
			(r) => r.name,
			(r) => r.label
		);
		if (!jobs.length) this.field("related_job").find("option").first().text(this.t.none_open || "");
	}

	bind() {
		this.$page.find(".sp-tab").on("click", (e) => this.set_kind($(e.currentTarget).data("kind")));
		this.$page.find(".sp-entry-reset").on("click", () => this.reset());
		this.$page.on("click", ".sp-log-booking", (e) => this.from_booking($(e.currentTarget).data("booking")));
		this.field("for_kind").on("change", () => this.show());
		this.field("expense_type").on("change", () => this.show());
		this.field("money_kind").on("change", () => this.show());
		this.field("received_method").on("change", () => this.show());
		this.$form.find(".sp-photo").on("change", (e) => this.upload_photo(e.target.files[0]));
		this.$form.find(".sp-record").on("click", () => this.record());
		this.$form.find(".sp-voice-file").on("change", (e) => this.upload_voice(e.target.files[0]));
		this.$form.on("submit", (e) => {
			e.preventDefault();
			this.save();
		});
		this.$page.on("click", ".sp-ask", (e) => this.ask_to_reopen($(e.currentTarget).closest("li").data()));
		// a new entry for a locked day: say so, and ask to reopen it from here (BUG-17)
		this.field("vehicle").on("change", () => this.check_lock());
		this.field("work_date").on("change", () => this.check_lock());
		this.$form.find(".sp-ask-day").on("click", () =>
			this.ask_to_reopen({ vehicle: this.field("vehicle").val(), work_date: this.field("work_date").val() })
		);
		this.$page.on("click", ".sp-change", (e) => this.open_entry($(e.currentTarget).closest("li").data("name")));
	}

	set_kind(kind) {
		this.kind = kind;
		this.$page.find(".sp-tab").each((_, el) => {
			$(el).toggleClass("btn-primary", $(el).data("kind") === kind).toggleClass("btn-default", $(el).data("kind") !== kind);
		});
		this.show();
	}

	code(list, name) {
		const row = (this.options[list] || []).find((r) => r.name === name);
		return row ? row.code : null;
	}

	show() {
		const kind = this.kind;
		this.$form.find(".sp-kind").each((_, el) => $(el).toggleClass("d-none", $(el).data("kind") !== kind));
		const for_kind = this.field("for_kind").val();
		this.$form.find(".sp-for").each((_, el) => $(el).toggleClass("d-none", $(el).data("for") !== for_kind));
		const expense = this.code("expense_types", this.field("expense_type").val());
		this.$form.find(".sp-oil").toggleClass("d-none", kind !== "Expense" || expense !== this.options.oil_code);
		this.$form.find(".sp-wage").toggleClass("d-none", kind !== "Expense" || expense !== this.options.wage_code);
		this.$form.find(".sp-amount").toggleClass("d-none", kind === "Job");
		const deposit = kind === "Money" && this.field("money_kind").val() === "Deposit";
		this.$form.find(".sp-received").toggleClass("d-none", deposit);
		this.$form.find(".sp-how").toggleClass("d-none", kind === "Expense");
		this.$form.find(".sp-method").toggleClass("d-none", deposit);
		const cash = this.code("methods", this.field("received_method").val()) === "CASH";
		this.$form.find(".sp-account").toggleClass("d-none", !deposit && cash);
	}

	reset() {
		this.editing = null;
		this.$form[0].reset();
		this.$form.find('input[type="hidden"]').val("");
		this.field("vehicle").val(this.options.my_vehicle || this.options.vehicles[0]?.name || "");
		this.field("work_date").val(this.options.today).attr("max", this.options.today);
		this.field("received_method").val(this.options.methods.find((m) => m.code === "CASH")?.name || "");
		this.$form.find(".sp-photo-state, .sp-voice-state").text("");
		this.$page.find(".sp-entry-title").text(this.t.new_entry || "");
		this.$page.find(".sp-entry-reset").addClass("d-none");
		this.$page.find(".sp-tab").prop("disabled", false);
		this.set_kind("Job");
		this.check_lock();
	}

	// SP-109 on the light page (BUG-17): the day's lock, with the way to ask to reopen it
	async check_lock() {
		const $lock = this.$form.find(".sp-day-lock").addClass("d-none");
		const $save = this.$form.find(".sp-save").prop("disabled", false);
		const vehicle = this.field("vehicle").val();
		const work_date = this.field("work_date").val();
		if (!vehicle || !work_date || this.editing) return;
		const { message: state } = await frappe.call({ method: `${SP_FL}.lock_state`, args: { vehicle, work_date } });
		// the day changed while asking (typing a date passes through others): a later check answers
		if (vehicle !== this.field("vehicle").val() || work_date !== this.field("work_date").val()) return;
		if (!state || !state.locked) return;
		if (state.blocked) $save.prop("disabled", true);
		$lock.find(".sp-day-lock-text").text(state.request ? `${this.t.locked} · ${this.t.waiting}` : this.t.locked);
		$lock.find(".sp-ask-day").toggleClass("d-none", Boolean(state.request));
		$lock.removeClass("d-none");
	}

	from_booking(name) {
		const booking = this.options.bookings.find((b) => b.name === name);
		this.reset();
		this.set_kind("Job");
		this.field("booking").val(name);
		if (booking) {
			this.field("vehicle").val(booking.vehicle);
			this.field("place").val(booking.place || "");
			this.$page.find(".sp-entry-title").text(`${booking.job} · ${booking.who}`);
		}
		this.$form[0].scrollIntoView({ behavior: "smooth" });
	}

	values() {
		const values = {};
		[...SP_COMMON_FIELDS, ...SP_KIND_FIELDS[this.kind]].forEach((name) => {
			const $f = this.field(name);
			if (!$f.length || ($f.closest(".d-none").length && !["booking", "photo", "voice_note"].includes(name))) return;
			let value = $f.val();
			if (value === "" || value === null || value === undefined) return;
			if (SP_NUMBERS.includes(name)) value = parseFloat(value);
			values[name] = value;
		});
		return values;
	}

	async save() {
		const $result = this.$form.find(".sp-result").removeClass("d-none alert-success alert-danger");
		const $button = this.$form.find(".sp-save").prop("disabled", true);
		try {
			const values = this.values();
			if (this.editing) {
				await frappe.call({ method: `${SP_FP}.update_entry`, args: { name: this.editing, values } });
				$result.addClass("alert-success").text(this.t.changed || "");
			} else {
				values.entry_kind = this.kind;
				values.client_uuid = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
				const { message } = await frappe.call({ method: `${SP_FE}.save_entry`, args: { values } });
				$result.addClass("alert-success").text(`${this.t.saved || ""}: ${message}`);
			}
			this.reset();
			this.load_entries();
		} catch (e) {
			$result.addClass("alert-danger").text(this.t.failed || "");
		} finally {
			$button.prop("disabled", false);
			if (!this.editing) this.check_lock(); // a refusal for a locked day shows how to ask (BUG-17)
		}
	}

	async load_entries() {
		const esc = sp_esc;
		const { message: rows } = await frappe.call({ method: `${SP_FP}.entries` });
		const $list = this.$page.find(".sp-field-entries").empty();
		rows.forEach((row) => {
			const $li = $(`<li class="sp-field-entry mb-2 d-flex justify-content-between align-items-center"></li>`)
				.attr("data-name", row.name)
				.attr("data-vehicle", row.vehicle)
				.attr("data-work_date", row.work_date);
			$li.append(`<div>${row.locked ? `<span class="sp-field-lock" title="${esc(this.t.locked)}" aria-label="${esc(this.t.locked)}">🔒</span> ` : ""}
				<b>${esc(row.kind_label)}</b> · ${esc(row.date_label)} · ${esc(row.status_label)}
				<div class="small text-muted">${esc(row.summary || "")}${row.amount ? ` · ${esc(row.amount_label)}` : ""}</div></div>`);
			if (row.locked && row.request) {
				$li.append(`<span class="small text-warning">${esc(this.t.waiting)}</span>`);
			} else if (row.locked) {
				$li.append(`<button type="button" class="btn btn-sm btn-warning sp-ask">${esc(this.t.ask)}</button>`);
			} else {
				$li.append(`<button type="button" class="btn btn-sm btn-default sp-change">${esc(this.t.change)}</button>`);
			}
			$list.append($li);
		});
	}

	async open_entry(name) {
		const { message: doc } = await frappe.call({ method: `${SP_FP}.entry`, args: { name } });
		if (doc.locked) return this.load_entries();
		this.reset();
		this.set_kind(doc.entry_kind);
		this.editing = doc.name;
		Object.entries(doc).forEach(([key, value]) => {
			const $f = this.field(key);
			if ($f.length && value !== null && value !== undefined) $f.val(value);
		});
		if (doc.money_kind === "Received" && doc.related_job && !this.field("related_job").val()) {
			this.field("related_job").append(`<option value="${sp_esc(doc.related_job)}">${sp_esc(doc.related_job)}</option>`).val(doc.related_job);
		}
		this.$page.find(".sp-tab").prop("disabled", true);
		this.$page.find(".sp-entry-title").text((this.t.editing || "{0}").replace("{0}", doc.name));
		this.$page.find(".sp-entry-reset").removeClass("d-none");
		this.show();
		this.$form[0].scrollIntoView({ behavior: "smooth" });
	}

	ask_to_reopen({ vehicle, work_date }) {
		const reason = window.prompt(this.t.reason || "");
		if (!reason || !reason.trim()) return;
		frappe
			.call({ method: `${SP_FL}.ask_to_reopen`, args: { vehicle, work_date, reason: reason.trim() } })
			.then(() => {
				this.$form.find(".sp-result").removeClass("d-none alert-danger").addClass("alert-success").text(this.t.sent || "");
				this.load_entries();
				this.check_lock();
			});
	}

	// --- media ---------------------------------------------------------------------------------

	async upload(file, method = "upload_file") {
		const data = new FormData();
		data.append("file", file, file.name);
		data.append("is_private", 1);
		data.append("folder", "Home");
		const response = await fetch(`/api/method/${method}`, {
			method: "POST",
			body: data,
			headers: { "X-Frappe-CSRF-Token": frappe.csrf_token || window.csrf_token },
		});
		if (!response.ok) throw new Error(this.t.failed);
		const { message } = await response.json();
		return typeof message === "string" ? message : message.file_url;
	}

	async shrink(file) {
		if (!file.type.startsWith("image/") || !window.createImageBitmap) return file;
		const image = await createImageBitmap(file);
		const scale = Math.min(1, SP_PHOTO_SIDE / Math.max(image.width, image.height));
		const canvas = document.createElement("canvas");
		canvas.width = Math.round(image.width * scale);
		canvas.height = Math.round(image.height * scale);
		canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
		const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", SP_PHOTO_QUALITY));
		return blob ? new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
	}

	async upload_photo(file) {
		if (!file) return;
		const $state = this.$form.find(".sp-photo-state").text(this.t.uploading);
		try {
			this.field("photo").val(await this.upload(await this.shrink(file)));
			$state.text(this.t.uploaded);
		} catch (e) {
			$state.text(this.t.failed);
		}
	}

	async upload_voice(file) {
		if (!file) return;
		const $state = this.$form.find(".sp-voice-state").text(this.t.uploading);
		try {
			// a website user may upload only images and documents to upload_file
			this.field("voice_note").val(await this.upload(file, `${SP_FP}.upload_voice`));
			$state.text(this.t.uploaded);
		} catch (e) {
			$state.text(this.t.failed);
		}
	}

	async record() {
		const $button = this.$form.find(".sp-record");
		if (this.recorder) {
			this.recorder.stop();
			return;
		}
		if (!navigator.mediaDevices || !window.MediaRecorder) {
			this.$form.find(".sp-voice-file").trigger("click");
			return;
		}
		let stream;
		try {
			stream = await navigator.mediaDevices.getUserMedia({ audio: true });
		} catch (e) {
			this.$form.find(".sp-voice-file").trigger("click");
			return;
		}
		const type = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
		const recorder = new MediaRecorder(stream, type ? { mimeType: type, audioBitsPerSecond: SP_VOICE_BITS } : {});
		const chunks = [];
		recorder.ondataavailable = (e) => chunks.push(e.data);
		recorder.onstop = () => {
			stream.getTracks().forEach((t) => t.stop());
			this.recorder = null;
			$button.text(this.t.record).removeClass("btn-danger");
			const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
			this.upload_voice(new File([blob], `voice-${Date.now()}.webm`, { type: blob.type }));
		};
		this.recorder = recorder;
		recorder.start();
		$button.text(this.t.recording).addClass("btn-danger");
	}
}
