export function selectMissingDemoDocuments(parserResults, existingIds) {
  const existing = new Set(existingIds);
  return parserResults.filter((result) => !existing.has(result.document_id));
}
