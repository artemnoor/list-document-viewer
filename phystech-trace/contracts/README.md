# Shared data contracts

`versions.json` is the version registry. The source schemas are the parser boundary contract (`parser-to-extraction-v1.schema.json`), the original Linking 1.2.0 schema for Structured Extraction (`structured-extraction-1.2.0.schema.json`), and the original Linking 1.2.0 result (`document-linking-1.2.0.schema.json`). The two 1.2.0 schemas are imported verbatim from the Linking release pinned in `versions.json`; contract tests verify byte identity with its retained release copies.

Parser output is intentionally an extensible object: the existing parser's Docling and native Office fields are preserved as-is. Required stable identifiers and the PDF/XLSX provenance fields are checked at the boundary. Extraction validates the raw parser shape with its existing adapter and validates its result with both its native Zod schema and the shared 1.2.0 JSON Schema. Linking validates its input and output with its release Zod schemas; contract tests ensure those schemas continue to match the shared JSON Schemas.

Additive fields are accepted within major versions and preserved by the services. Missing required fields, repeated document IDs, incompatible major versions, invalid PDF boxes, and malformed spreadsheet locators produce field-level diagnostics. A new major contract requires an explicit adapter and schema version; do not rewrite stored results in place.
