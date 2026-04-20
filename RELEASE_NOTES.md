# Release Notes

## 2026-04-20

- Removed support for the legacy `no_referrer` sentinel value.
- Orders that were previously marked with `no_referrer` are now represented with a null (`None`) referrer.
- Added a data migration to convert existing `no_referrer` sales records to null referrers and remove the legacy referrer record.
- Updated referrer assignment screens, analytics, and filters to rely on standard null/unassigned semantics.
