import type { Link } from "./types";

/** Only coalesce identical typed, directed, row-scoped proposals with identical evidence.
 * Semantic equivalence is not inferred from amounts, labels, or document types. */
export function mergeTaskLinks(links: Link[]): Link[] {
  const merged = new Map<string, Link>();
  for (const link of links) {
    const key = JSON.stringify([link.relationship_type, link.source_document_id, link.target_document_id,
      link.source_row_id ?? null, link.target_row_id ?? null,
      link.evidence.map(item => [item.source.path, item.target.path]).sort()]);
    const previous = merged.get(key);
    if (!previous) { merged.set(key, structuredClone(link)); continue; }
    previous.confidence = Math.min(previous.confidence, link.confidence);
    if (previous.status !== link.status) previous.status = "review";
    previous.conflicts = [...new Set([...previous.conflicts, ...link.conflicts])];
    previous.alternatives = [...new Set([...(previous.alternatives ?? []), ...(link.alternatives ?? [])])];
    if (previous.explanation !== link.explanation) previous.explanation += `\n${link.explanation}`;
  }
  return [...merged.values()];
}
