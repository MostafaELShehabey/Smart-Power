// Smart Power display formats (SP-22): times on a 12-hour clock with ص/م (AM/PM in English).
// Display only: time inputs and stored values stay on Frappe's 24-hour clock.
// Frappe keeps moment on the "en" locale, so format("A") is AM or PM and __() translates it.
(() => {
	const TIME_INPUTS = ["HH:mm:ss.SSSSSS", "HH:mm:ss", "HH:mm"];
	const clock = (m) => `${m.format("hh:mm")} ${__(m.format("A"))}`;
	const formatters = frappe.form.formatters;

	formatters.Time = function (value) {
		if (!value) return "";
		const m = moment(value, TIME_INPUTS, true);
		return m.isValid() ? clock(m) : value;
	};

	formatters.Datetime = function (value) {
		if (!value) return "";
		const m = moment(frappe.datetime.convert_to_user_tz(value));
		return `${m.format(frappe.boot.sysdefaults.date_format.toUpperCase())} ${clock(m)}`;
	};
})();

// A location map opens on Egypt, not on Frappe's default centre in India (BUG-4): the whole
// country, since the company has no single base the sites cluster around.
Object.assign(frappe.utils.map_defaults, { center: [26.8, 30.8], zoom: 6 }); // sp-allow-number: Egypt's centre and a country-wide zoom
