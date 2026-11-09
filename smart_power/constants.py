"""Names the code relies on. Mechanism only: no business numbers live here (tech plan section 1)."""

# Developer-owned modules. Fixtures are exported and synced only for these (SP-164).
SP_MODULES = (
	"SP Core",
	"SP Sales",
	"SP Quotes",
	"SP Stations",
	"SP Stock",
	"SP Finance",
	"SP Winch",
	"SP Site",
)

# Where the admin's own customizations land. It is a custom Module Def, never exported,
# never synced, and a deploy refuses to overwrite anything in it.
ADMIN_MODULE = "Smart Power Admin"

# Prefixes reserved for developer-owned records.
DEV_FIELD_PREFIX = "sp_"
DEV_NAME_PREFIX = "SP "

# DocTypes whose records carry a `module` field and can be owned by the developer or the admin.
MODULE_OWNED_DOCTYPES = (
	"Custom Field",
	"Property Setter",
	"Print Format",
	"Notification",
	"Client Script",
	"Server Script",
	"Report",
)

# DocTypes without a `module` field: ownership is decided by the "SP " name prefix.
PREFIX_OWNED_DOCTYPES = (
	"Role",
	"Role Profile",
	"Workflow",
)

SETTINGS_DOCTYPE = "Smart Power Settings"
