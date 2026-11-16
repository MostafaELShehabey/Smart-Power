"""The record pattern (SP-45): what every main record's page shows above its fields.

    owner_fields()   {doctype: {fieldname: role kind}}, the owners shown as chips; a chip's
                     history is the record's Owner History rows of that role kind
    boot(bootinfo)   puts owner_fields() on the boot for sp_form.js

The status bar reads the record's Workflow (its states, and the transitions open to the user)
and the primary button is registered per doctype in its form script (sp.form.register_primary).
"""

from smart_power.sp_sales.case import OWNER_FIELDS
from smart_power.sp_stations.station import OWNER_LABELS


def owner_fields() -> dict[str, dict[str, str]]:
	return {"SP Case": dict(OWNER_FIELDS), "SP Station": dict(OWNER_LABELS)}


def boot(bootinfo) -> None:
	bootinfo.sp_owner_fields = owner_fields()
