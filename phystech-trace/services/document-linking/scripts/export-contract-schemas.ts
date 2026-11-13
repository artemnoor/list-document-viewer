import { writeFileSync } from "node:fs";
import { z } from "zod";
import { extractionSchema } from "../src/contracts/input";
import { linkingOutputSchema } from "../src/contracts/output";
import { INPUT_CONTRACT_VERSION, OUTPUT_CONTRACT_VERSION, STRUCTURED_EXTRACTION_BASELINE } from "../src/contracts/registry";
writeFileSync("contracts/input.schema.json", `${JSON.stringify({ $schema: "https://json-schema.org/draft/2020-12/schema", $id: "https://artemnoor.github.io/kfz-document-linking/contracts/input.schema.json", title: "Structured Extraction 1.2.0 result", ...z.toJSONSchema(extractionSchema, { reused: "ref" }) }, null, 2)}\n`);
writeFileSync("contracts/output.schema.json", `${JSON.stringify({ $schema: "https://json-schema.org/draft/2020-12/schema", $id: "https://artemnoor.github.io/kfz-document-linking/contracts/output.schema.json", title: "Document Linking result 1.2.0", ...z.toJSONSchema(linkingOutputSchema, { reused: "ref" }) }, null, 2)}\n`);
writeFileSync("contracts/versions.json", `${JSON.stringify({ input_contract_version: INPUT_CONTRACT_VERSION, output_contract_version: OUTPUT_CONTRACT_VERSION, structured_extraction_baseline: STRUCTURED_EXTRACTION_BASELINE, compatibility: { accepted_schema_versions: "1.2.x and additive 1.x", breaking_upstream_major_requires_new_adapter: true } }, null, 2)}\n`);
