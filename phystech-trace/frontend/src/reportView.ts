import type { TraceProject, Provenance } from './types';

export type ReportSource = { document_id: string; file_name: string; value?: any; source_value?: any; provenance?: Provenance | null; source_path?: string; inclusion_reason?: string };
export type ReportRow = { id: string; title: string; originalLabel: string; status: string; actual: any; expected: any; difference: any; currency?: string | null; sources: ReportSource[]; actualSource?: ReportSource; reason: string; isTotal: boolean };
export const money = (value: any, currency = 'RUB') => {
  if (value === null || value === undefined || value === '') return '—';
  const raw = typeof value === 'object' ? value.amount : value;
  if (raw === null || raw === undefined || raw === '' || !Number.isFinite(Number(raw))) return '—';
  return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(raw)) + (currency === 'RUB' ? ' ₽' : currency ? ' ' + currency : '');
};
export function sourceFor(project: TraceProject, source: any): ReportSource {
  const id = source.document_id || source.provenance?.document_id || project.documents.find(d => d.file_name === source.file_name)?.document_id || '';
  return { ...source, document_id: id, file_name: source.file_name || project.documents.find(d => d.document_id === id)?.file_name || 'Подтверждающий документ', value: source.value ?? source.normalized_value ?? source.raw_value, source_value: source.source_value ?? source.raw_value };
}
export function titleFor(label: string, subcolumn?: number) {
  const lower = label.toLowerCase();
  let title = /итого|[hн]то[гr]о/i.test(lower) ? 'Общий итог' : /оплат.*труд/.test(lower) ? 'Оплата труда' : /страхов.*взнос/.test(lower) ? 'Страховые взносы' : /общепроизводствен/.test(lower) ? 'Общепроизводственные затраты' : /общехозяйствен/.test(lower) ? 'Общехозяйственные затраты' : /трудоемк|трудоёмк/.test(lower) ? 'Трудоёмкость' : /материальн/.test(lower) ? 'Материальные затраты' : label.replace(/,?\s*\d+ этап.*$/i, '').replace(/\(Статья калькуляции[^)]*\)/ig, '').trim();
  if (subcolumn !== undefined) title += ` · расшифровка, столбец ${subcolumn + 1}`;
  return title;
}
export function reportRows(project: TraceProject): ReportRow[] {
  const local = project.financial_audit;
  return (local?.indicators || project.verification_result?.indicators || []).map((item: any): ReportRow => {
    const label = item.label || item.semantic_key || 'Показатель отчёта';
    const raw = item.actual_source;
    const subcolumn = /[Пп]одколонка/.test(item.reason || '') ? raw?.provenance?.column_index : undefined;
    const sourceItems = local ? item.sources || [] : item.evidence?.used_sources || [];
    return { id: item.target_id, title: titleFor(label, subcolumn), originalLabel: label, status: item.status, actual: local ? item.actual : item.actual?.normalized_value ?? item.actual?.source_value, expected: local ? item.expected : item.expected?.normalized_value ?? item.expected?.source_value, difference: local ? item.difference : item.difference?.absolute, currency: local ? item.currency : item.actual?.currency, sources: sourceItems.map((s: any) => sourceFor(project, s)), actualSource: raw ? sourceFor(project, raw) : item.actual ? sourceFor(project, item.actual) : undefined, reason: item.reason || item.uncertainty?.status_reason || '', isTotal: /итого|[hн]то[гr]о|общий итог/i.test(label) };
  });
}
export const statusLabels: Record<string, string> = { matched: 'Совпадает', mismatch: 'Расхождение', insufficient_data: 'Нет подтверждения', needs_review: 'Нужна проверка', manual_review: 'Нужна проверка', not_applicable: 'Не применяется' };
export function excludedDocuments(project: TraceProject) {
  const input = project.financial_audit?.documents || project.document_findings || [];
  const seen = new Set<string>();
  return input.filter((d: any) => {
    if (d.included || d.category === 'included') return false;
    const key = `${d.file_name}:${d.category}`;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  });
}
export const findingLabels: Record<string, string> = { duplicate_operation: 'Дубликат', wrong_period: 'Другой период', incorrect_document_link: 'Другой договор', needs_review: 'Нужна проверка', missing_supporting_document: 'Недостаточно данных' };
