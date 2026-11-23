// Copyright (c) 2026, Smart Power and contributors
// For license information, please see license.txt

// The admin's guide to Frappe's own no-code tools (SP-182, decision 24): each task step by step,
// with a button that opens the tool. The guide is in Arabic, as the admin works in Arabic.
const SP_GUIDE = [
	{
		title: "إضافة سؤال إجباري لطلب عرض السعر لنوع نظام واحد",
		route: ["List", "SP List Value", { list_name: "System Type" }],
		steps: [
			"افتح «القوائم» ← نوع النظام، واختر النوع (مثلاً: طلمبة).",
			"في جدول «أسئلة طلب عرض السعر» أضف صفًا: الاسم بالإنجليزي، والاسم بالعربي، والنوع (رقم، نص، اختيار …).",
			"علِّم «إجباري» ليصبح السؤال مطلوبًا لهذا النوع وحده، ثم احفظ.",
			"افتح «طلب عرض سعر» جديد واختر النوع: يظهر السؤال، ولا يُحفظ الطلب بدونه.",
		],
	},
	{
		title: "إضافة حقل لأي نموذج",
		route: ["Form", "Customize Form"],
		steps: [
			"افتح «تخصيص النموذج» واختر النموذج (مثلاً: العميل).",
			"أضف صفًا في جدول الحقول: العنوان، والنوع، ومكانه بين الحقول.",
			"«إجباري» يجعله مطلوبًا، و«مخفي» يخفيه، و«يعتمد على» يُظهره بشرط.",
			"احفظ «تحديث»: يظهر الحقل للجميع فورًا.",
		],
	},
	{
		title: "إضافة حالة أو خطوة اعتماد",
		route: ["List", "Workflow"],
		steps: [
			"افتح «مسارات العمل» واختر مسار السجل (مثلاً: الحالة أو المحطة).",
			"أضف الحالة في جدول الحالات، ومن له تعديلها.",
			"أضف الانتقال: من حالة إلى حالة، والإجراء، والدور الذي يقوم به.",
			"احفظ، ثم جرّب على سجل تجريبي.",
		],
	},
	{
		title: "تغيير مستوى قاعدة (إيقاف / تنبيه / منع)",
		route: ["List", "SP Rule Setting"],
		steps: [
			"افتح «القواعد» واختر القاعدة.",
			"غيّر المستوى: «إيقاف» لا يفعل شيئًا، «تنبيه» يُظهر رسالة، «منع» يوقف الحفظ.",
			"عدّل الحدود إن وُجدت (مثلاً: أقصى خصم) واحفظ.",
		],
	},
	{
		title: "تعديل نموذج طباعة",
		route: ["print-format-builder"],
		steps: [
			"نصوص عرض السعر والعقد والضمان في «قوالب المستندات»: عدّل النص والبيانات ثم انشر.",
			"لأي مستند آخر افتح «منشئ نماذج الطباعة» واختر المستند، واسحب الحقول وعدّل العناوين.",
			"احفظ، ثم اطبع سجلًا لتتأكد من الشكل.",
		],
	},
	{
		title: "بناء تقرير وحفظه",
		route: ["List", "Report"],
		steps: [
			"افتح أي قائمة (مثلاً: المحطات) ثم اختر عرض «تقرير».",
			"اختر الأعمدة والفلاتر والترتيب، وأضف «تجميع» إن احتجت.",
			"من القائمة اختر «حفظ باسم» ليبقى التقرير في «التقارير».",
		],
	},
	{
		title: "الصلاحيات",
		route: ["permission-manager"],
		steps: [
			"«صلاحيات الأدوار»: ماذا يرى كل دور ويعدّل في كل نموذج.",
			"«صلاحيات المستخدمين»: قصر مستخدم على سجلات بعينها (مثلاً: فرع أو مخزن).",
			"غيّر بحذر: الأدوار والملفات التعريفية تُدار عادة من «المستخدمون والأدوار».",
		],
	},
];

const SP_GUARDRAILS = [
	"كل ما تغيّره بهذه الأدوات يُحفظ باسم «Smart Power Admin»، فلا يمسحه أي تحديث للنظام.",
	"الأسماء التي تبدأ بـ sp_ أو «SP » محجوزة للمطوّر؛ اختر اسمًا آخر.",
	"كل تغيير يظهر في «سجل التدقيق» بمن غيّره ومتى.",
	"القواعد الأساسية (القيد المتوازن، وعدم تعديل القيد المرحّل) في الكود نفسه، ولا تُطفأ من أي إعداد.",
];

frappe.pages["sp-admin-guide"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Admin Guide"), single_column: true });
	const $body = $('<div class="sp-admin-guide" dir="rtl"></div>').appendTo(page.main);
	const esc = frappe.utils.escape_html;
	SP_GUIDE.forEach((task, i) => {
		const $card = $(`
			<div class="frappe-card" style="padding: var(--padding-md); margin-bottom: var(--margin-md);">
				<h4>${i + 1}. ${esc(task.title)}</h4>
				<ol>${task.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
				<button class="btn btn-default btn-sm">${__("Open")}</button>
			</div>`).appendTo($body);
		$card.find("button").on("click", () => frappe.set_route(...task.route));
	});
	$(`
		<div class="frappe-card" style="padding: var(--padding-md);">
			<h4>${__("Guardrails")}</h4>
			<ul>${SP_GUARDRAILS.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
		</div>`).appendTo($body);
};
