import kfz from "../../data/parser-results/kfz-2026-q1.json";
import contract from "../../data/parser-results/contract-2026-0315.json";
import act from "../../data/parser-results/act-2026-0424.json";
import invoice from "../../data/parser-results/invoice-2026-0408.json";
import addendum from "../../data/parser-results/addendum-2026-04.json";
import registry from "../../data/parser-results/registry-2026-04.json";

export const demoParserResults: Array<Record<string, unknown>> = [kfz, contract, act, invoice, addendum, registry];

export function demoDocumentRecord(parserJson: Record<string, unknown>) {
  return {
    id: String(parserJson.document_id),
    title: String(parserJson.title ?? parserJson.file_name ?? parserJson.document_id),
    fileName: String(parserJson.file_name ?? `${parserJson.document_id}.json`),
    format: String(parserJson.format ?? parserJson.source_extension ?? "JSON").replace(/^\./, "").toUpperCase(),
    isDemo: true,
    isSynthetic: true,
    inputVersion: 1,
    extractionVersion: 0,
    parserJson: JSON.stringify(parserJson),
  };
}
