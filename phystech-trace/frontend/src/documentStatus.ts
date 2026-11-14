import type { StageState, TraceDocument } from './types';

export type DocumentStatus = 'done' | 'processing' | 'waiting' | 'error';

export function documentStatus(doc: TraceDocument, extraction?: StageState): DocumentStatus {
  if (doc.extraction_id) return 'done';
  if (doc.parser_state === 'running' || doc.extraction_state === 'running' ||
    (extraction?.status === 'running' && (extraction.current_document_id
      ? extraction.current_document_id === doc.id : extraction.current_file === doc.file_name))) return 'processing';
  if (doc.parser_state === 'error' || doc.parser_error || doc.extraction_error) return 'error';
  return 'waiting';
}

export function documentStatusLabel(doc: TraceDocument, extraction?: StageState): string {
  const status = documentStatus(doc, extraction);
  if (status === 'done') return 'Обработан';
  if (status === 'error') return doc.has_parser_result ? 'Ошибка извлечения данных' : 'Ошибка распознавания';
  if (status === 'processing') return doc.has_parser_result ? 'Извлекаем данные' : 'Распознаём текст';
  return doc.has_parser_result ? 'Ожидает извлечения данных' : 'Ещё не обработан';
}
