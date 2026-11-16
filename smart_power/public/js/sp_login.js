// Login page (SP-36, G1): Forgot password takes an email or a mobile and sends a request to the
// admin (smart_power.sp_core.login.request_password_reset); there is no self-service email.
// Website pages do not load the app's translations, so the few words here carry both languages.
/* global login */
(function () {
	if (window.location.pathname !== "/login") return;
	const lang = document.documentElement.lang || "ar";
	const words = {
		ar: {
			label: "البريد الإلكتروني أو الموبايل",
			hint: "اكتب بريدك أو رقم موبايلك، وسيعطيك المدير كلمة مرور جديدة.",
			send: "إرسال إلى المدير",
		},
		en: {
			label: "Email or mobile",
			hint: "Type your email or mobile; the admin will give you a new password.",
			send: "Send to the admin",
		},
	}[lang.startsWith("ar") ? "ar" : "en"];

	$(window).on("load", function () {
		const $form = $(".form-forgot");
		if (!$form.length || typeof login === "undefined") return;
		$("label[for='forgot_email']").text(words.label);
		$("section.for-forgot .page-card-head p, section.for-forgot .text-ink-gray-5:not(label)")
			.first()
			.text(words.hint);
		$("#forgot_email").attr({ type: "text", inputmode: "email", placeholder: "01xxxxxxxxx" });
		$(".btn-forgot").text(words.send);
		$("#forgot_email")
			.off("input")
			.on("input", function () {
				$(".btn-forgot").text(words.send).prop("disabled", !$(this).val().trim());
			});
		$form.off("submit").on("submit", function (event) {
			event.preventDefault();
			const user = ($("#forgot_email").val() || "").trim();
			if (!user) return false;
			login.call(
				{ cmd: "smart_power.sp_core.login.request_password_reset", user: user, _lang: lang },
				null,
				"/",
				"section.for-forgot .login-success-banner .es-alert__title"
			);
			return false;
		});
	});
})();
