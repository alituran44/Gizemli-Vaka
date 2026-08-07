---
name: Adding columns to existing tables
description: db.create_all() will NOT add new columns to tables that already exist — you must ALTER TABLE manually.
---

# Schema changes on existing tables

`db.create_all()` (called in `initialize_app`) only creates tables that don't yet exist. It does **not** alter existing tables to add newly-declared columns.

**Why:** adding a column to an already-created model (e.g. new `dealer_code` / `dealer_qr_template_id` on the pre-existing `TeamPurchase`) silently has no effect on the DB; the next insert then fails with "column does not exist".

**How to apply:** after adding a column to an existing model, run an explicit `ALTER TABLE <table> ADD COLUMN IF NOT EXISTS ...` against `$DATABASE_URL` in BOTH dev and (at deploy time) production. Brand-new tables are fine — `create_all` handles those. Also remember production is a separate database, so the same ALTER must be applied there.
