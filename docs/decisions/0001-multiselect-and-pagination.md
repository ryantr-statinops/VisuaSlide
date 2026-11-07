# Multiselect analysis and paginated reporting

**Status — Accepted.** Approved for implementation on 7 November 2026. Offline and live verification are separate delivery gates.

## Analysis

Declare multiselect categories, aliases and a separator in TOML. Match complete choices from the start of the remaining input, longest first, with a separator or end boundary. A configured choice may contain the separator. Deduplicate within a response and preserve configured category order. Allow a trailing separator. Report unrecognized input through validation counts and safe issue codes.

Keep raw API values unchanged. Store prepared choices as nullable Arrow lists of strings in Parquet, including an explicit list type for entirely missing columns. DuckDB owns aggregation. Nonmissing denominators count answering records, while all-response denominators include retained records with missing answers. Retain zero-count options and calculation precision.

Numeric allowed-value sets are optional. Existing unbounded numeric schemas remain valid.

## Reporting

Keep complete analysis tables immutable. Project frequency and multiselect tables into pages of at most ten categories. Preserve the full-question denominator on every page. Keep the original object keys on page one and use deterministic additional page keys. Each page owns a reporting tab, linked chart where applicable, and managed slide content.

Bootstrap and publication use the same page rules. Record managed page ownership before Google side effects, reconcile uncertain creates, and remove obsolete registered pages without touching unregistered user slides. Missing previously published managed elements remain errors.

Persist the desired publication content and plan before publishing. Resume uses that artifact and its layout version. Runs predating this feature use the legacy renderer when no publication artifact exists. A legacy layout overflow requires a new refresh.

## Compatibility and verification

Retain support for existing TOML, snapshots, scalar Parquet columns and one-page IDs. Normalize additive configuration defaults when comparing legacy configuration hashes. New reports use layout version 2 and SDK version 0.2.0.

Unit, integration and opt-in sandbox tests are added in the final test phase. Verify Parquet round-trips, hand-calculated percentages, 10/11/13/20 category boundaries, repeated publication, partial failures and legacy resume. Google acceptance includes reading actual output content and inspecting every rendered slide.
