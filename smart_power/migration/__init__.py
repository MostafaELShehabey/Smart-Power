"""Go-live master-data migration from Excel (E17, SP-159).

Each script reads one filled template, upserts by its natural key, and writes a CSV report of
every row (created, updated, merged, unchanged, skipped or error, with the reason). A dry run
does all of it and rolls it back, so its report shows what the real run will do. Run them as
the admin from bench, in this order (each later file refers to the earlier ones):

    suppliers     smart_power.migration.suppliers.run       payment terms; the consignment owner
    items         smart_power.migration.items.run           SP-165's per-group templates: codes,
                                                            specs and dated supplier prices
    design        smart_power.migration.design.run          DESIGN.xlsx: panel and drive specs
    customers     smart_power.migration.customers.run       one customer per mobile
                  smart_power.migration.customers.from_statement
                                                            the station customers of the yearly
                                                            statement, featured
    leads         smart_power.migration.leads.run           the marketing agent's leads, with
                                                            their campaign
    workers       smart_power.migration.workers.run         names, mobiles, wages
    vehicles      smart_power.migration.vehicles.run        odometer and oil interval
    settings      smart_power.sp_site.settings_files.import_folder   the SETTING folder (SP-98)

For example:

    bench --site <site> execute smart_power.migration.customers.template --kwargs "{'out': '/tmp/customers.xlsx'}"
    bench --site <site> execute smart_power.migration.customers.run --kwargs "{'path': '/tmp/customers.xlsx'}"
    bench --site <site> execute smart_power.migration.customers.run --kwargs "{'path': '/tmp/customers.xlsx', 'dry_run': 0}"

Every run returns its counts (source rows and what happened to them) and the report's path, for
the data owner's sign-off.
"""
