<template>
	<div class="sp-dt">
		<section class="sp-dt-card sp-dt-quote">
			<div ref="quoteField" class="sp-dt-quote-field"></div>
			<p class="text-muted">{{ __("Push to quote writes a result into the quote's design inputs and recalculates it.") }}</p>
		</section>

		<ol class="sp-dt-tabs">
			<li v-for="(t, i) in tabs" :key="t.key">
				<button class="btn btn-xs" :class="tab === i ? 'btn-primary' : 'btn-default'" @click="tab = i">
					{{ i + 1 }}. {{ t.label }}
				</button>
			</li>
		</ol>

		<!-- 1. string calculator -->
		<section v-show="tab === 0" class="sp-dt-card">
			<div class="sp-dt-fields">
				<label>
					{{ __("Solar Panel") }}
					<select v-model="str.panel" class="form-control" @change="clear('string')">
						<option value=""></option>
						<option v-for="p in cat.panels" :key="p.name" :value="p.name">{{ itemLabel(p, p.sp_watt && `${p.sp_watt} W`) }}</option>
					</select>
				</label>
				<label>
					{{ __("Drive or Inverter") }}
					<select v-model="str.drive" class="form-control" @change="clear('string')">
						<option value=""></option>
						<option v-for="d in cat.drives" :key="d.name" :value="d.name">{{ itemLabel(d, d.sp_kw && `${d.sp_kw} kW`) }}</option>
					</select>
				</label>
				<label>{{ __("Panels per String") }}<input v-model="str.n" type="number" min="1" class="form-control" @input="clear('string')" /></label>
				<label>{{ __("Number of Strings") }}<input v-model="str.strings" type="number" min="1" class="form-control" @input="clear('string')" /></label>
				<label>{{ __("Minimum Temperature (°C)") }}<input v-model="str.tmin" type="number" class="form-control" @input="clear('string')" /></label>
				<label>{{ __("Maximum Temperature (°C)") }}<input v-model="str.tmax" type="number" class="form-control" @input="clear('string')" /></label>
			</div>
			<dl v-if="panel || drive" class="sp-dt-specs">
				<div v-if="panel"><dt>{{ __("Solar Panel") }}</dt><dd>Vmp {{ panel.sp_vmp || "—" }} V · Voc {{ panel.sp_voc || "—" }} V · Isc {{ panel.sp_isc || "—" }} A · {{ coeffText }}</dd></div>
				<div v-if="drive"><dt>{{ __("Drive or Inverter") }}</dt><dd>MPPT {{ drive.sp_mppt_min || "—" }}–{{ drive.sp_mppt_max || "—" }} V · {{ __("Max DC") }} {{ drive.sp_max_dc_v || "—" }} V</dd></div>
			</dl>
			<div class="sp-dt-actions">
				<button class="btn btn-default btn-sm" :disabled="!strReady" @click="runString">{{ __("Run the Check") }}</button>
				<button class="btn btn-primary btn-sm" :disabled="!result.string?.ok || !quote" @click="push('string')">{{ __("Push to Quote") }}</button>
			</div>
			<div v-if="result.string" class="sp-dt-result">
				<p class="sp-dt-verdict" :class="result.string.ok ? 'ok' : 'fail'">
					{{ result.string.ok ? __("All checks pass") : __("The design fails a check") }}
				</p>
				<table class="table table-sm">
					<thead><tr><th>{{ __("String Check") }}</th><th>{{ __("Value (V)") }}</th><th>{{ __("Limit (V)") }}</th><th>{{ __("Result") }}</th></tr></thead>
					<tbody>
						<tr v-for="c in result.string.checks" :key="c.key">
							<td>{{ c.label }}</td>
							<td class="sp-dt-num">{{ c.value }}</td>
							<td class="sp-dt-num">{{ c.limit }}</td>
							<td :class="c.ok ? 'ok' : 'fail'">{{ c.ok ? __("OK") : __("Fail") }}</td>
						</tr>
					</tbody>
				</table>
				<p>{{ __("Total") }}: <b>{{ fmt(result.string.kwp, 2) }} kWp</b> · {{ __("Array Isc") }}: {{ fmt(result.string.array_isc, 2) }} A</p>
			</div>
		</section>

		<!-- 2. pump selector -->
		<section v-show="tab === 1" class="sp-dt-card">
			<div class="sp-dt-fields">
				<label>{{ __("Water Level / Pump Depth (m)") }}<input v-model="pmp.depth" type="number" min="0" class="form-control" @input="clear('pump')" /></label>
				<label>{{ __("Losses (m)") }}<input v-model="pmp.losses" type="number" min="0" class="form-control" @input="clear('pump')" /></label>
				<label>{{ __("Flow (m³/h)") }}<input v-model="pmp.flow" type="number" min="0" class="form-control" @input="clear('pump')" /></label>
				<label>{{ __("Required Head (m)") }}<input :value="head || ''" type="number" class="form-control" disabled /></label>
			</div>
			<div class="sp-dt-actions">
				<button class="btn btn-default btn-sm" :disabled="!(head > 0 && pmp.flow > 0)" @click="runPump">{{ __("Find Pumps") }}</button>
				<button class="btn btn-primary btn-sm" :disabled="!result.pump || !quote" @click="push('pump')">{{ __("Push to Quote") }}</button>
			</div>
			<div v-if="result.pump" class="sp-dt-result">
				<p v-if="!result.pump.pumps.length" class="text-muted">
					{{ __("No pump curve covers {0} m at {1} m³/h ({2} pumps have a curve).", [result.pump.head, result.pump.flow, result.pump.with_curve]) }}
				</p>
				<table v-else class="table table-sm">
					<thead><tr><th></th><th>{{ __("Pump") }}</th><th>{{ __("HP") }}</th><th>{{ __("Head at this Flow (m)") }}</th><th>{{ __("Drive Need (kW)") }}</th><th>{{ __("Drives that Fit") }}</th></tr></thead>
					<tbody>
						<tr v-for="p in result.pump.pumps" :key="p.item">
							<td><input v-model="pmp.pick" type="radio" :value="p.item" /></td>
							<td>{{ p.item_name }}<small v-if="p.brand" class="text-muted"> · {{ p.brand }}</small></td>
							<td class="sp-dt-num">{{ p.hp || "—" }}</td>
							<td class="sp-dt-num">{{ p.head_at_flow }}</td>
							<td class="sp-dt-num">{{ p.drive_kw }}</td>
							<td>{{ p.drives.map((d) => `${d.item_name} (${d.kw} kW)`).join("، ") || __("None in the catalogue") }}</td>
						</tr>
					</tbody>
				</table>
				<p class="text-muted">{{ __("Only pumps with a manufacturer's curve are listed.") }}</p>
			</div>
		</section>

		<!-- 3. off-grid sizing -->
		<section v-show="tab === 2" class="sp-dt-card">
			<table class="table table-sm sp-dt-loads">
				<thead><tr><th>{{ __("Appliance") }}</th><th>{{ __("Qty") }}</th><th>{{ __("Watts") }}</th><th>{{ __("Day Hours") }}</th><th>{{ __("Night Hours") }}</th><th></th></tr></thead>
				<tbody>
					<tr v-for="(r, i) in off.loads" :key="i">
						<td><input v-model="r.load" class="form-control" @input="clear('offgrid')" /></td>
						<td><input v-model="r.qty" type="number" min="0" class="form-control" @input="clear('offgrid')" /></td>
						<td><input v-model="r.watts" type="number" min="0" class="form-control" @input="clear('offgrid')" /></td>
						<td><input v-model="r.day_hours" type="number" min="0" class="form-control" @input="clear('offgrid')" /></td>
						<td><input v-model="r.night_hours" type="number" min="0" class="form-control" @input="clear('offgrid')" /></td>
						<td><button class="btn btn-xs btn-default" @click="removeLoad(i)">✕</button></td>
					</tr>
				</tbody>
			</table>
			<button class="btn btn-xs btn-default" @click="addLoad">{{ __("Add Load") }}</button>
			<div class="sp-dt-fields">
				<label v-for="(f, key) in cat.factors" :key="key">{{ f.label }}<input v-model="off.factors[key]" type="number" class="form-control" @input="clear('offgrid')" /></label>
			</div>
			<div class="sp-dt-actions">
				<button class="btn btn-default btn-sm" @click="runOffgrid">{{ __("Size the System") }}</button>
				<button class="btn btn-primary btn-sm" :disabled="!result.offgrid || !quote" @click="push('offgrid')">{{ __("Push to Quote") }}</button>
			</div>
			<dl v-if="result.offgrid" class="sp-dt-specs sp-dt-result">
				<div><dt>{{ __("Peak Load") }}</dt><dd>{{ fmt(result.offgrid.load_w) }} W</dd></div>
				<div><dt>{{ __("Daily Energy") }}</dt><dd>{{ fmt(result.offgrid.day_wh + result.offgrid.night_wh) }} Wh</dd></div>
				<div><dt>{{ __("Night Energy") }}</dt><dd>{{ fmt(result.offgrid.night_wh) }} Wh</dd></div>
				<div><dt>{{ __("Panels") }}</dt><dd>{{ __("{0} panels in {1} strings (need {2} W)", [result.offgrid.panels, result.offgrid.strings, fmt(result.offgrid.panel_w, 1)]) }}</dd></div>
				<div><dt>{{ __("Inverter") }}</dt><dd>{{ fmt(result.offgrid.inverter_kw, 3) }} kW</dd></div>
				<div><dt>{{ __("Batteries") }}</dt><dd>{{ __("{0} Ah: {1} batteries of {2} Ah", [fmt(result.offgrid.battery_ah, 1), result.offgrid.batteries, result.offgrid.factors.battery_unit_ah]) }}</dd></div>
			</dl>
		</section>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";

const props = defineProps({ page: Object, quote: String });
const API = "smart_power.sp_quotes.design";
const __ = window.__;
const tabs = [
	{ key: "string", label: __("String Calculator") },
	{ key: "pump", label: __("Pump Selector") },
	{ key: "offgrid", label: __("Off-grid Sizing") },
];
const tab = ref(0);
const quote = ref(props.quote || "");
const quoteField = ref(null);
const cat = reactive({ panels: [], drives: [], factors: {}, default_coeff: null });
const str = reactive({ panel: "", drive: "", n: "", strings: "", tmin: "", tmax: "" });
const pmp = reactive({ depth: "", losses: "", flow: "", pick: "" });
const off = reactive({ loads: [blankLoad()], factors: {} });
const result = reactive({ string: null, pump: null, offgrid: null });

function blankLoad() {
	return { load: "", qty: 1, watts: "", day_hours: "", night_hours: "" };
}

const panel = computed(() => cat.panels.find((p) => p.name === str.panel));
const drive = computed(() => cat.drives.find((d) => d.name === str.drive));
const coeffText = computed(() => `${panel.value?.sp_temp_coeff_voc || cat.default_coeff} %/°C`);
const strReady = computed(() => str.panel && str.drive && str.n > 0 && str.strings > 0 && str.tmin !== "" && str.tmax !== "");
const head = computed(() => flt(pmp.depth) + flt(pmp.losses));
const fmt = (v, digits = 0) => format_number(v || 0, null, digits);
const itemLabel = (i, spec) => [i.item_name || i.name, spec].filter(Boolean).join(" · ");

function clear(key) {
	result[key] = null;
}
function addLoad() {
	off.loads.push(blankLoad());
}
function removeLoad(i) {
	off.loads.splice(i, 1);
	if (!off.loads.length) addLoad();
	clear("offgrid");
}

async function call(method, args) {
	const { message } = await frappe.call({ method: `${API}.${method}`, args, freeze: true });
	return message;
}

async function runString() {
	result.string = await call("string_check", { ...str });
}
async function runPump() {
	result.pump = await call("select_pumps", { head: head.value, flow: pmp.flow });
	pmp.pick = result.pump.pumps[0]?.item || "";
}
const loadRows = () => off.loads.filter((r) => flt(r.watts) > 0);
async function runOffgrid() {
	result.offgrid = await call("size_offgrid", { loads: loadRows(), factors: { ...off.factors } });
}

function valuesOf(key) {
	if (key === "string") return { ...str };
	if (key === "pump") return { head: head.value, flow: pmp.flow, pump: pmp.pick };
	return { loads: loadRows(), factors: { ...off.factors } };
}

async function push(key) {
	const message = await frappe.call({
		method: `${API}.push`,
		args: { quote: quote.value, tool: key, values: valuesOf(key) },
		freeze: true,
		freeze_message: __("Recalculating the quote…"),
	}).then((r) => r.message);
	frappe.show_alert({ message: __("Quote {0} updated and recalculated.", [message.quote]), indicator: "green" });
	frappe.route_options = { sp_reload: 1 };
	frappe.set_route("sp-quote-builder", message.quote);
}

onMounted(async () => {
	const control = frappe.ui.form.make_control({
		parent: quoteField.value,
		df: {
			fieldtype: "Link",
			fieldname: "quote",
			options: "Quotation",
			label: __("Quote"),
			description: __("A draft quote of a case."),
			get_query: () => ({ filters: { docstatus: 0, sp_case: ["is", "set"] } }),
			onchange: () => (quote.value = control.get_value() || ""),
		},
		render_input: true,
	});
	if (quote.value) control.set_value(quote.value);
	Object.assign(cat, await call("catalogue", {}));
	for (const [key, f] of Object.entries(cat.factors)) off.factors[key] = f.value ?? "";
});
</script>

<style scoped>
.sp-dt {
	display: grid;
	gap: 16px;
}
.sp-dt-card {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 8px;
	padding: 16px;
}
.sp-dt-quote-field {
	max-width: 360px;
}
.sp-dt-tabs {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	margin: 0;
	padding: 0;
	list-style: none;
}
.sp-dt-fields {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
	gap: 12px;
	margin-top: 12px;
}
.sp-dt-specs div {
	display: flex;
	justify-content: space-between;
	gap: 8px;
	margin: 0 0 6px;
}
.sp-dt-specs dd {
	margin: 0;
	font-weight: 600;
}
.sp-dt-specs {
	margin-top: 12px;
}
.sp-dt-actions {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	margin-top: 12px;
}
.sp-dt-result {
	margin-top: 12px;
	overflow-x: auto;
}
.sp-dt-num {
	white-space: nowrap;
}
.sp-dt-loads input {
	min-width: 84px;
}
.ok {
	color: var(--text-on-green);
	font-weight: 600;
}
.fail {
	color: var(--text-on-red);
	font-weight: 600;
}
.sp-dt-verdict {
	font-size: 16px;
}
</style>
