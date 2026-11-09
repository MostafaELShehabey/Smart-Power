"""The role catalogue from the Miro board (36 keys, as of 8-11-2026) and the person-type profiles.

Roles are small and do one job each; a person holds several and the admin moves them (decision 24).
Each SP role sits on top of the ERPNext roles that give it the standard permissions it needs.
This module is the source the role fixtures are built from (`devtools.roles.build`), and the
constants other code uses to check a role by its key.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoleDef:
	key: str
	label_ar: str
	desk_access: bool = True
	erpnext_roles: tuple[str, ...] = field(default_factory=tuple)
	name: str | None = None

	@property
	def role_name(self) -> str:
		return self.name or "SP " + self.key.replace("_", " ").title()


ROLES: tuple[RoleDef, ...] = (
	# Admin and finance
	RoleDef(
		"admin",
		"الأدمن",
		erpnext_roles=(
			"System Manager",
			"Accounts Manager",
			"Sales Manager",
			"Purchase Manager",
			"Stock Manager",
			"Projects Manager",
			"Item Manager",
			"Sales Master Manager",
			"Purchase Master Manager",
		),
	),
	RoleDef("accountant", "المحاسب", erpnext_roles=("Accounts Manager", "Accounts User")),
	RoleDef("commission_manager", "العمولات", erpnext_roles=("Accounts User",)),
	RoleDef("collection_officer", "التحصيل", erpnext_roles=("Accounts User",)),
	RoleDef("supplier_accounts", "حسابات الموردين", erpnext_roles=("Accounts User", "Purchase User")),
	RoleDef("bank_financing", "التمويل البنكي", erpnext_roles=("Accounts User",)),
	RoleDef("hr_payroll", "الموارد البشرية والمرتبات", erpnext_roles=("HR User",), name="SP HR Payroll"),
	RoleDef("tax_insurance", "الضرائب والتأمينات", erpnext_roles=("Accounts User",)),
	RoleDef("fleet_assets", "الأصول والمركبات", erpnext_roles=("Fleet Manager",)),
	# Intake and follow-up
	RoleDef("lead_intake", "استقبال العملاء", erpnext_roles=("Sales User",)),
	RoleDef("customer_followup", "متابعة العملاء", erpnext_roles=("Sales User",)),
	RoleDef("site_survey", "معاينة الموقع", erpnext_roles=("Projects User",)),
	# Marketing
	RoleDef("marketing_agent", "التسويق", erpnext_roles=("Sales User",)),
	# Quotes and prices (system_designer is merged into quote_creator, decision 67; the key stays)
	RoleDef("system_designer", "مصمم الأنظمة", erpnext_roles=("Sales User",)),
	RoleDef("quote_creator", "إعداد عروض الأسعار", erpnext_roles=("Sales User",)),
	RoleDef("catalog_manager", "الأصناف والكتالوجات", erpnext_roles=("Item Manager",)),
	RoleDef("pricing_manager", "لستة الأسعار", erpnext_roles=("Item Manager", "Sales Master Manager")),
	# Contracts, stations, buying
	RoleDef("contract_manager", "العقود", erpnext_roles=("Sales User",)),
	RoleDef("project_manager", "مدير المشروعات", erpnext_roles=("Projects Manager", "Projects User")),
	RoleDef("purchase_officer", "المشتريات", erpnext_roles=("Purchase User",)),
	RoleDef("receipt_confirmer", "تأكيد الاستلام", erpnext_roles=("Stock User", "Purchase User")),
	# Stores and showroom
	RoleDef("main_store_keeper", "أمين المخزن الرئيسي", erpnext_roles=("Stock User",)),
	RoleDef("showroom_store_keeper", "أمين مخزن المعرض", erpnext_roles=("Stock User",)),
	RoleDef("site_receiver", "استلام الموقع", erpnext_roles=("Stock User",)),
	RoleDef("showroom_sales", "مبيعات المعرض", erpnext_roles=("Sales User", "Stock User")),
	RoleDef("showroom_cashier", "خزنة المعرض", erpnext_roles=("Accounts User",)),
	# Site and service
	RoleDef("installation_manager", "مدير التركيبات", erpnext_roles=("Projects User",)),
	RoleDef("installation_technician", "فني تركيبات", erpnext_roles=("Projects User",)),
	RoleDef("commissioning_programmer", "البرمجة والتشغيل", erpnext_roles=("Projects User",)),
	RoleDef("warranty_service", "الضمان والصيانة", erpnext_roles=("Maintenance User",)),
	RoleDef("regulatory_compliance", "التراخيص والتأهيل"),
	# Winch and Jumbo
	RoleDef("winch_manager", "مسئول الونش", erpnext_roles=("Fleet Manager",)),
	RoleDef("winch_reviewer", "مراجعة الونش"),
	RoleDef("winch_operator", "سواق الونش", desk_access=False),
	RoleDef("driver", "سواق العربية", desk_access=False),
	# Money held
	RoleDef("custody_holder", "صاحب عهدة"),
)

BY_KEY: dict[str, RoleDef] = {r.key: r for r in ROLES}

# Roles whose users get the light mobile entry instead of the desk (SP-34, SP-180).
LIGHT_ENTRY_ROLES = tuple(r.role_name for r in ROLES if not r.desk_access)


def role(key: str) -> str:
	"""Role name for a catalogue key, e.g. role("quote_creator") -> "SP Quote Creator"."""
	return BY_KEY[key].role_name


@dataclass(frozen=True)
class ProfileDef:
	name: str
	label_ar: str
	held_by: str
	keys: tuple[str, ...]

	def roles(self) -> list[str]:
		names = {role(k) for k in self.keys}
		for k in self.keys:
			names.update(BY_KEY[k].erpnext_roles)
		return sorted(names)


# One profile per person-type, from the Miro team table (8-11-2026). The admin clones these for new hires.
PROFILES: tuple[ProfileDef, ...] = (
	ProfileDef(
		"SP Owner and Admin",
		"المدير وصاحب الشركة",
		"محمد سليمان",
		(
			"admin",
			"accountant",
			"commission_manager",
			"collection_officer",
			"supplier_accounts",
			"bank_financing",
			"hr_payroll",
			"tax_insurance",
			"fleet_assets",
		),
	),
	ProfileDef(
		"SP Installations Manager",
		"مدير التركيبات",
		"مصطفى",
		(
			"installation_manager",
			"site_survey",
			"site_receiver",
			"commissioning_programmer",
			"warranty_service",
			"custody_holder",
		),
	),
	ProfileDef(
		"SP Technical Office",
		"المكتب الفني",
		"آية",
		(
			"quote_creator",
			"receipt_confirmer",
			"catalog_manager",
			"pricing_manager",
			"regulatory_compliance",
			"custody_holder",
		),
	),
	ProfileDef(
		"SP Projects Manager",
		"مدير المشروعات",
		"أميرة",
		(
			"quote_creator",
			"contract_manager",
			"project_manager",
			"purchase_officer",
			"pricing_manager",
			"winch_reviewer",
		),
	),
	ProfileDef(
		"SP Showroom and Winch",
		"مبيعات المعرض والونش",
		"محمد حسين",
		(
			"lead_intake",
			"customer_followup",
			"showroom_sales",
			"showroom_cashier",
			"showroom_store_keeper",
			"winch_manager",
		),
	),
	ProfileDef(
		"SP Marketing and Quotes",
		"ماركتنج وإعداد عروض",
		"مها",
		("marketing_agent", "lead_intake", "quote_creator", "custody_holder"),
	),
	ProfileDef(
		"SP Call Center",
		"كول سنتر ومتابعة العملاء",
		"كاميليا",
		("lead_intake", "customer_followup"),
	),
	ProfileDef(
		"SP Store and Installations",
		"تركيبات وأمين مخازن",
		"محمد جابر",
		("main_store_keeper", "installation_technician"),
	),
	ProfileDef("SP Jumbo Driver", "سواق العربية (جامبو)", "سواق الجامبو", ("driver",)),
	ProfileDef("SP Winch Operator", "سواق الونش", "سواق الونش", ("winch_operator",)),
)
