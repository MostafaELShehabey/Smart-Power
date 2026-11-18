<template>
	<div v-if="data" class="sp-qb">
		<div class="sp-qb-main">
			<ol class="sp-qb-steps">
				<li v-for="(s, i) in steps" :key="s" :class="{ active: step === i }">
					<button class="btn btn-xs" :class="step === i ? 'btn-primary' : 'btn-default'" @click="step = i">
						{{ i + 1 }}. {{ s }}
					</button>
				</li>
			</ol>

			<!-- 1. header -->
			<section v-show="step === 0" class="sp-qb-card">
				<dl class="sp-qb-facts">
					<div v-for="f in facts" :key="f.label">
						<dt>{{ f.label }}</dt>
						<dd>{{ f.value || "—" }}</dd>
					</div>
				</dl>
				<div class="sp-qb-fields">
					<label>
						{{ __("Valid Till") }}
						<input v-model="header.valid_till" type="date" class="form-control" :disabled="!canEdit" @change="touch" />
					</label>
					<label>
						{{ __("Project Scope") }}
						<select v-model="header.sp_scope" class="form-control" :disabled="!canEdit" @change="touch">
							<option value="Supply and install">{{ __("Supply and install") }}</option>
							<option value="Supply only">{{ __("Supply only") }}</option>
						</select>
					</label>
				</div>
			</section>

			<!-- 2. design inputs -->
			<section v-show="step === 1" class="sp-qb-card">
				<p v-if="!data.inputs.length" class="text-muted">
					{{ __("This system type has no calculation template yet: add its lines in the Items step.") }}
				</p>
				<div class="sp-qb-fields">
					<label v-for="i in data.inputs" :key="i.input_key">
						{{ i.label }}<span v-if="i.reqd" class="text-danger"> *</span>
						<select
							v-if="i.input_type === 'Select'"
							v-model="inputs[i.input_key]"
							class="form-control"
							:disabled="!canEdit"
							@change="touch"
						>
							<option v-for="o in optionsOf(i)" :key="o" :value="o">{{ o }}</option>
						</select>
						<input
							v-else
							v-model="inputs[i.input_key]"
							:type="i.input_type === 'Data' ? 'text' : 'number'"
							class="form-control"
							:disabled="!canEdit"
							@input="touch"
						/>
						<small v-if="i.help" class="text-muted">{{ i.help }}</small>
					</label>
				</div>
			</section>

			<!-- 3. items -->
			<section v-show="step === 2" class="sp-qb-card">
				<p v-for="r in data.rules" :key="r.key" class="sp-qb-note" :class="{ block: r.level === 'Block' }">{{ r.message }}</p>
				<div v-if="canEdit && data.pending.length" class="sp-qb-pending">
					<b>{{ __("Lines waiting for an item") }}</b>
					<div v-for="p in data.pending" :key="p.line_key">
						<span>{{ p.item_name }} · {{ p.qty }}</span>
						<button class="btn btn-xs btn-primary" @click="changeItem(p)">{{ __("Choose item") }}</button>
					</div>
				</div>
				<div class="sp-qb-table">
					<table class="table table-sm">
						<thead>
							<tr>
								<th>{{ __("Item") }}</th>
								<th>{{ __("Unit") }}</th>
								<th>{{ __("Qty") }}</th>
								<th v-if="internals">{{ __("Cost") }}</th>
								<th v-if="internals">{{ __("Markup %") }}</th>
								<th>{{ __("Sell") }}</th>
								<th>{{ __("Total") }}</th>
								<th v-if="internals">{{ __("Profit") }}</th>
								<th>{{ __("Print Group") }}</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							<template v-for="(l, i) in data.lines" :key="l.line_key || i">
							<tr v-if="l.section && l.section !== data.lines[i - 1]?.section" class="sp-qb-section">
								<td :colspan="internals ? 10 : 7">{{ l.section }}</td>
							</tr>
							<tr :class="{ 'sp-qb-hidden': l.kind === 'Commission' }">
								<td>
									<input v-if="!l.line_key" v-model="l.item_name" class="form-control input-xs" :disabled="!canEdit" @change="touch" />
									<span v-else>{{ l.item_name }}</span>
									<span v-if="l.kind === 'Commission'" class="sp-qb-tag">{{ __("Hidden") }}</span>
									<span v-if="l.kind === 'Winch'" class="sp-qb-tag">{{ __("Winch") }}</span>
									<span
										v-if="['stale', 'aging'].includes(l.price_status)"
										class="sp-qb-clock"
										:class="l.price_status"
										:title="__('{0} days', [l.price_age])"
										>🕒</span
									>
									<button
										v-if="canEdit && l.line_key && !l.kind"
										class="sp-qb-tag"
										:title="__('Choose another item')"
										@click="changeItem(l)"
									>
										{{ __("Change") }}
									</button>
									<button
										v-if="canEdit && overrides[l.line_key]?.item_code"
										class="sp-qb-tag manual"
										:title="__('Back to the default item')"
										@click="clearItem(l)"
									>
										{{ __("Manual") }} ✕
									</button>
									<div v-if="l.stock && !l.kind" class="small text-muted">
										{{ __("Company Stock") }}: {{ l.stock.company }} · {{ __("Consignment") }}: {{ l.stock.consignment }}
									</div>
									<div v-for="n in notesOf(l)" :key="n.message" class="small sp-qb-note">{{ n.message }}</div>
								</td>
								<td>{{ l.uom }}</td>
								<td class="sp-qb-num">
									<input
										:value="l.qty"
										type="number"
										class="form-control input-xs"
										:disabled="!canEdit"
										@change="setQty(l, $event.target.value)"
									/>
									<button v-if="l.line_key && l.manual" class="sp-qb-tag manual" :title="__('Back to the calculated quantity')" :disabled="!canEdit" @click="clearQty(l)">
										{{ __("Manual") }} ✕
									</button>
								</td>
								<td v-if="internals" class="sp-qb-num">
									<input
										:value="l.cost"
										type="number"
										class="form-control input-xs"
										:disabled="!canEdit"
										@change="setPrice(l, 'cost', $event.target.value)"
									/>
								</td>
								<td v-if="internals" class="sp-qb-num">
									<input
										v-if="l.markup_editable"
										:value="l.markup"
										type="number"
										class="form-control input-xs"
										:disabled="!canEdit"
										@change="setMarkup(l, $event.target)"
									/>
								</td>
								<td class="sp-qb-num">
									<input
										:value="l.rate"
										type="number"
										class="form-control input-xs"
										:disabled="!canEdit || l.kind === 'Commission' || (l.line_key && !l.rate_editable)"
										@change="setPrice(l, 'rate', $event.target.value)"
									/>
								</td>
								<td class="sp-qb-num">{{ money(l.amount) }}</td>
								<td v-if="internals" class="sp-qb-num">{{ money(l.profit) }}</td>
								<td>
									<input :value="l.merge" class="form-control input-xs" :disabled="!canEdit" @change="setMerge(l, $event.target.value)" />
								</td>
								<td>
									<button v-if="!l.line_key && canEdit" class="btn btn-xs btn-default" :title="__('Remove')" @click="removeLine(i)">✕</button>
								</td>
							</tr>
							</template>
						</tbody>
					</table>
				</div>
				<div v-if="canEdit" class="sp-qb-actions">
					<button class="btn btn-xs btn-default" @click="addLine('Manual')">{{ __("Add a Line") }}</button>
					<button class="btn btn-xs btn-default" @click="addLine('Winch')">{{ __("Add the Winch Line") }}</button>
					<button v-if="internals" class="btn btn-xs btn-default" @click="addLine('Commission')">{{ __("Add the Commission") }}</button>
				</div>
			</section>

			<!-- 4. options -->
			<section v-show="step === 3" class="sp-qb-card">
				<table class="table table-sm">
					<tbody>
						<tr v-for="o in data.options" :key="o.name" :class="{ 'sp-qb-this': o.is_this }">
							<td>{{ __("Option") }} {{ o.label }}</td>
							<td>{{ __("Version") }} {{ o.version }}</td>
							<td>{{ __(o.status) }}</td>
							<td class="sp-qb-num">{{ money(o.total) }}</td>
							<td><button v-if="!o.is_this" class="btn btn-xs btn-default" @click="open(o.name)">{{ __("Open") }}</button></td>
						</tr>
					</tbody>
				</table>
				<button class="btn btn-xs btn-default" @click="newOption">{{ __("Duplicate as Another Option") }}</button>
			</section>

			<!-- 5. payment plans -->
			<section v-show="step === 4" class="sp-qb-card">
				<p v-if="!data.plans.length" class="text-muted">{{ __("No payment plans are active.") }}</p>
				<label v-if="data.plans.length" class="sp-qb-plan">
					<input v-model="header.sp_payment_plan" type="radio" value="" :disabled="!canEdit" @change="touch" />
					{{ __("Cash") }} · {{ money(data.total) }}
				</label>
				<div v-for="p in data.plans" :key="p.template" class="sp-qb-plan">
					<label>
						<input v-model="header.sp_payment_plan" type="radio" :value="p.template" :disabled="!canEdit" @change="touch" />
						<b>{{ p.template }}</b> · {{ money(p.total) }}
					</label>
					<div class="small text-muted">
						{{ __("Down Payment") }} {{ money(p.down) }} · {{ p.installments }} × {{ money(p.installment) }} ·
						{{ __("Cheque Value") }} {{ money(p.cheque) }}
						<span v-if="internals"> · {{ __("Net Margin %") }} {{ pct(p.net_margin_pct) }}</span>
					</div>
					<details class="small">
						<summary>{{ __("Schedule") }}</summary>
						<div v-for="r in p.schedule" :key="r.due_date">{{ date(r.due_date) }} · {{ money(r.amount) }}</div>
					</details>
				</div>
			</section>

			<!-- 6. terms and preview -->
			<section v-show="step === 5" class="sp-qb-card">
				<label class="sp-qb-wide">
					{{ __("Execution Period") }}
					<input v-model="header.sp_execution_period" class="form-control" :disabled="!canEdit" @change="touch" />
				</label>
				<!-- the admin's published template text, filled on the server (SP-134) -->
				<div v-for="(t, i) in data.terms" :key="i" class="sp-qb-term" v-html="t"></div>
				<button class="btn btn-xs btn-default" @click="preview">{{ __("Preview the PDF") }}</button>
				<iframe v-if="previewUrl" :src="previewUrl" class="sp-qb-preview" :title="__('Preview the PDF')"></iframe>
			</section>
		</div>

		<aside class="sp-qb-summary">
			<template v-if="data.summary">
				<h5>{{ __("Summary") }}</h5>
				<dl>
					<div><dt>{{ __("Total Cost") }}</dt><dd>{{ money(data.summary.cost) }}</dd></div>
					<div><dt>{{ __("Total Sell") }}</dt><dd>{{ money(data.summary.sell) }}</dd></div>
					<div><dt>{{ __("Profit") }}</dt><dd>{{ money(data.summary.profit) }}</dd></div>
					<div><dt>{{ __("Margin") }}</dt><dd>{{ pct(data.summary.margin) }}</dd></div>
					<div v-if="data.summary.price_per_kw"><dt>{{ __("Price per kW") }}</dt><dd>{{ money(data.summary.price_per_kw) }}</dd></div>
					<div v-if="data.summary.discount"><dt>{{ __("Discount") }}</dt><dd>{{ money(data.summary.discount) }}</dd></div>
				</dl>
				<span v-if="range" class="indicator-pill" :class="range.in_range ? 'green' : 'orange'">
					{{ range.in_range ? __("In range") : __("Out of range") }} ({{ range.min }}% – {{ range.max }}%)
				</span>
			</template>
			<template v-else>
				<h5>{{ __("Total") }}</h5>
				<p class="sp-qb-total">{{ money(data.total) }}</p>
			</template>
			<p class="small text-muted sp-qb-state">{{ stateText }}</p>
		</aside>
	</div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";

const props = defineProps({ page: Object, name: String });
const API = "smart_power.sp_quotes.builder";
const AUTOSAVE_MS = 20000; // sp-allow-number: the story's autosave
const RECALC_MS = 400; // sp-allow-number: wait for the typing to stop

const __ = window.__;
const steps = [__("Header"), __("Design Inputs"), __("Items"), __("Options"), __("Payment Plans"), __("Terms and Preview")];
const step = ref(0);
const data = ref(null);
const inputs = reactive({});
const overrides = ref({});
const previewUrl = ref("");
const merge = reactive({});
const reasons = reactive({});
const header = reactive({});
const dirty = ref(false);
const busy = ref(false);
const savedAt = ref(null);
let recalcTimer = null;
let autosaveTimer = null;
let latest = 0; // only the newest recalculation may reach the screen
let saveFailed = false; // a refused save waits for the next change, not the next 20 seconds

const canEdit = computed(() => !!data.value?.can_edit);
const internals = computed(() => !!data.value?.summary);
const range = computed(() => data.value?.summary?.range);
const notesOf = (line) => (data.value?.notes || []).filter((n) => n.level === "warn" && line.line_key && n.line_key === line.line_key);
const stateText = computed(() => {
	if (busy.value) return __("Working…");
	if (dirty.value) return __("Not saved yet");
	return savedAt.value ? __("Saved at {0}", [savedAt.value]) : "";
});
const facts = computed(() => {
	const h = data.value.header;
	return [
		{ label: __("Quote"), value: `${h.name} · ${__("Option")} ${h.option || "A"} · ${__("Version")} ${h.version || 1}` },
		{ label: __("Customer"), value: h.customer_name },
		{ label: __("Mobile"), value: h.mobile },
		{ label: __("Customer Tier"), value: h.tier && __(h.tier) },
		{ label: __("Site"), value: h.site },
		{ label: __("Calculation Template"), value: h.template },
		{ label: __("Payment Method"), value: h.payment_method },
		{ label: __("Status"), value: h.status && __(h.status) },
	];
});

const money = (v) => format_currency(v || 0, data.value?.header.currency);
const pct = (v) => `${flt(v, 1)}%`;
const date = (v) => frappe.datetime.str_to_user(v);
const optionsOf = (i) => (i.options || "").split("\n").filter(Boolean);

function show(payload) {
	data.value = payload;
	for (const i of payload.inputs) if (!(i.input_key in inputs)) inputs[i.input_key] = i.value;
	overrides.value = payload.overrides || {};
	for (const l of payload.lines) if (l.line_key) merge[l.line_key] = l.merge || "";
	for (const f of ["valid_till", "sp_scope", "sp_payment_plan", "sp_execution_period"]) header[f] = payload.header[f] || "";
	header.sp_scope = header.sp_scope || "Supply and install";
}

function values() {
	return {
		inputs: { ...inputs },
		overrides: overrides.value,
		header: { ...header },
		merge: { ...merge },
		reasons: { ...reasons },
		hand_lines: data.value.lines
			.filter((l) => !l.line_key)
			.map((l) => ({
				item_code: l.item_code,
				item_name: l.item_name,
				qty: l.qty,
				rate: l.rate,
				sp_cost: l.cost,
				sp_line_kind: l.kind,
				sp_merge_group: l.merge,
			})),
	};
}

function touch() {
	if (!canEdit.value) return;
	dirty.value = true;
	saveFailed = false;
	latest += 1;
	clearTimeout(recalcTimer);
	recalcTimer = setTimeout(recalc, RECALC_MS);
}

async function recalc() {
	const mine = ++latest;
	busy.value = true;
	try {
		const { message } = await frappe.call({ method: `${API}.recalc`, args: { name: props.name, data: values() } });
		if (mine === latest) show(message);
	} finally {
		busy.value = false;
	}
}

async function save(silent) {
	if (!canEdit.value) return;
	clearTimeout(recalcTimer);
	latest += 1;
	busy.value = true;
	saveFailed = true;
	try {
		const { message } = await frappe.call({
			method: `${API}.save`,
			args: { name: props.name, data: values(), modified: data.value.header.modified },
		});
		show(message);
		saveFailed = false;
		dirty.value = false;
		savedAt.value = frappe.datetime.now_time();
		if (!silent) frappe.show_alert({ message: __("Saved"), indicator: "green" });
	} finally {
		busy.value = false;
	}
}

function override(key) {
	overrides.value[key] = overrides.value[key] || {};
	return overrides.value[key];
}

function setQty(line, value) {
	if (line.line_key) override(line.line_key).qty = flt(value);
	else line.qty = flt(value);
	touch();
}

function clearQty(line) {
	delete override(line.line_key).qty;
	touch();
}

function changeItem(line) {
	frappe.prompt(
		[
			{
				fieldname: "item_code",
				fieldtype: "Link",
				options: "Item",
				label: __("Item"),
				default: line.item_code,
				reqd: 1,
				get_query: () =>
					line.item_group ? { filters: { item_group: ["descendants of (inclusive)", line.item_group] } } : {},
			},
		],
		(v) => {
			override(line.line_key).item_code = v.item_code;
			touch();
		},
		__("Choose another item")
	);
}

function clearItem(line) {
	delete override(line.line_key).item_code;
	touch();
}

function setPrice(line, field, value) {
	if (line.line_key) override(line.line_key)[field] = flt(value);
	else line[field] = flt(value);
	touch();
}

// any change of a markup needs its reason (decision 43); without one the old value stays
function setMarkup(line, input) {
	const value = flt(input.value);
	input.value = line.markup;
	frappe.prompt(
		[{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 }],
		(v) => {
			reasons[line.line_key] = v.reason;
			override(line.line_key).markup = value;
			line.markup = value;
			touch();
		},
		__("Why change the markup?")
	);
}

function setMerge(line, value) {
	if (line.line_key) merge[line.line_key] = value;
	else line.merge = value;
	touch();
}

function removeLine(index) {
	data.value.lines.splice(index, 1);
	touch();
}

function addLine(kind) {
	const commission = kind === "Commission";
	frappe.prompt(
		[
			{ fieldname: "item_name", fieldtype: "Data", label: __("Description"), reqd: 1 },
			{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), default: 1, reqd: 1 },
			{ fieldname: "amount", fieldtype: "Currency", label: commission ? __("Commission") : __("Sell"), reqd: 1 },
		],
		(v) => {
			data.value.lines.push({
				item_name: v.item_name,
				qty: v.qty,
				rate: commission ? 0 : v.amount,
				cost: commission ? v.amount : 0,
				kind,
			});
			touch();
		},
		commission ? __("Add the Commission") : kind === "Winch" ? __("Add the Winch Line") : __("Add a Line")
	);
}

function open(name) {
	frappe.set_route("sp-quote-builder", name);
}

async function newOption() {
	await save(true);
	const { message } = await frappe.call({
		method: "smart_power.sp_sales.quotation.new_option",
		args: { quotation: props.name },
		freeze: true,
	});
	open(message);
}

async function newVersion() {
	const { message } = await frappe.call({
		method: "smart_power.sp_sales.quotation.new_version",
		args: { quotation: props.name },
		freeze: true,
	});
	open(message);
}

async function preview() {
	await save(true);
	const q = new URLSearchParams({ doctype: "Quotation", name: props.name, format: "SP Quotation", _: Date.now() });
	previewUrl.value = `/printview?${q}`;
	step.value = steps.length - 1;
}

async function send() {
	await save(true);
	sp.sales.send_quote(props.name, data.value.header.docstatus, load);
}

function markLost() {
	sp.sales.lost_dialog(data.value.header.case, null, load);
}

async function load() {
	const { message } = await frappe.call({ method: `${API}.load`, args: { name: props.name } });
	show(message);
	actions();
}

function actions() {
	const page = props.page;
	page.clear_actions();
	page.clear_inner_toolbar();
	page.set_title(`${__("Quote Builder")}: ${data.value.header.name}`);
	if (canEdit.value) {
		page.set_primary_action(__("Send"), send);
		page.set_secondary_action(__("Save Draft"), () => save());
	} else {
		page.set_primary_action(__("Send Again"), send);
	}
	page.add_inner_button(__("Preview"), preview);
	page.add_inner_button(__("New Version"), newVersion);
	page.add_inner_button(__("Mark Lost"), markLost);
	page.add_inner_button(__("Open the Quote"), () => frappe.set_route("Form", "Quotation", props.name));
}

onMounted(async () => {
	props.page.sp_builder_dirty = () => dirty.value;
	await load();
	autosaveTimer = setInterval(() => {
		if (dirty.value && !busy.value && !saveFailed) save(true);
	}, AUTOSAVE_MS);
});

onBeforeUnmount(() => {
	clearInterval(autosaveTimer);
	clearTimeout(recalcTimer);
});
</script>

<style scoped>
.sp-qb {
	display: grid;
	grid-template-columns: minmax(0, 1fr) 260px;
	gap: 16px;
	align-items: start;
}
.sp-qb-steps {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	list-style: none;
	padding: 0;
	margin: 0 0 12px;
}
.sp-qb-card,
.sp-qb-summary {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 8px;
	padding: 16px;
}
.sp-qb-summary {
	position: sticky;
	top: 72px;
}
.sp-qb-summary dl div,
.sp-qb-facts div {
	display: flex;
	justify-content: space-between;
	gap: 8px;
	margin: 0 0 6px;
}
.sp-qb-summary dd,
.sp-qb-facts dd {
	margin: 0;
	font-weight: 600;
}
.sp-qb-facts {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
	gap: 0 24px;
}
.sp-qb-fields {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
	gap: 12px;
	margin-top: 12px;
}
.sp-qb-table {
	overflow-x: auto;
}
.sp-qb-table input {
	min-width: 84px;
}
.sp-qb-num {
	white-space: nowrap;
}
.sp-qb-tag {
	display: inline-block;
	margin-inline-start: 6px;
	padding: 0 6px;
	border: 0;
	border-radius: 8px;
	font-size: 11px;
	background: var(--bg-gray);
}
.sp-qb-tag.manual {
	background: var(--bg-orange);
	color: var(--text-on-orange);
}
.sp-qb-clock.stale {
	filter: hue-rotate(-40deg);
}
.sp-qb-hidden {
	background: var(--bg-light-gray);
}
.sp-qb-this {
	font-weight: 600;
}
.sp-qb-note {
	color: var(--text-on-orange);
	margin-bottom: 6px;
}
.sp-qb-note.block {
	color: var(--text-on-red);
}
.sp-qb-pending {
	margin-bottom: 12px;
	padding: 10px 12px;
	border: 1px solid var(--border-color);
	border-radius: 8px;
	background: var(--bg-orange);
}
.sp-qb-pending div {
	display: flex;
	justify-content: space-between;
	align-items: center;
	gap: 8px;
	margin-top: 6px;
}
.sp-qb-section td {
	background: var(--subtle-fg);
	font-weight: 600;
}
.sp-qb-preview {
	display: block;
	width: 100%;
	height: 70vh;
	margin-top: 12px;
	border: 1px solid var(--border-color);
}
.sp-qb-actions {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
}
.sp-qb-plan {
	display: block;
	padding: 8px 0;
	border-bottom: 1px solid var(--border-color);
}
.sp-qb-wide {
	display: block;
	max-width: 360px;
}
.sp-qb-term {
	margin: 12px 0;
}
.sp-qb-total {
	font-size: 20px;
	font-weight: 600;
}
.sp-qb-state {
	margin: 12px 0 0;
}
@media (max-width: 900px) {
	.sp-qb {
		grid-template-columns: minmax(0, 1fr);
	}
	.sp-qb-summary {
		position: static;
	}
}
</style>
