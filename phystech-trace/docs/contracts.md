# Контракты и совместимость

## Версии

Текущая матрица зафиксирована в [`contracts/versions.json`](../contracts/versions.json).

| Направление | Версия | Требования |
| --- | --- | --- |
| Parser → Extraction | `1.0.0` | Полное исходное Parser JSON; обязательны `document_id`, `source_extension`, `parts`. Добавляются trace metadata и parser storage ID. |
| Extraction → Linking | `1.2.0` | Схема upstream Linking; принимаются `1.2.x` и additive `1.x`; несовместимая major-версия отклоняется. |
| Linking result | `1.2.0` | Схема исходного графа связей и evidence; document/row IDs, raw/normalized values и provenance сохраняются. |

Схемы находятся в `contracts/`: Parser boundary, Structured Extraction 1.2.0 и Linking output 1.2.0. Схемы 1.2.0 перенесены verbatim из импорта Linking; автоматические проверки сравнивают их с release-копиями. Parser schema разрешает additive upstream поля Docling/OCR и проверяет обязательную форму, не переписывая исходные данные.

## Provenance

- `document_id` назначается Parser и проходит без изменения в extraction и `input_documents` Linking.
- `row_id` сохраняется от extraction строки до link endpoint, когда Linking его формирует.
- PDF locator сохраняет страницу, bbox, исходную/нормализованную системы координат и размер страницы, когда эти значения есть в Parser result.
- XLSX locator сохраняет `sheet_name` и `cell_address` (например, `Ведомость!C8`); формула, исходное и cached значения остаются рядом, как в Parser.
- Linking evidence сохраняет JSON path, raw/normalized values и provenance обоих концов связи.

## Ошибки и изменение версии

Сервисы возвращают 422 с `path` и `message` при несовместимом JSON, недостающих полях, повторном document ID и неподдерживаемой версии. Неполный Parser result сохраняется и отображается как частичный, но не передаётся дальше до проверки. Additive fields major версии сохраняются. Breaking schema change требует новой major-версии и адаптера; старые результаты молча не мигрируются.

## Проверки

`tests/contracts/test_contracts.py` проверяет JSON Schema, release identity и реальные fixtures. Extraction проверяет Parser boundary и свой output. Linking валидирует вход и output исходными Zod-схемами. Gateway повторно проверяет межсервисные данные и сохранённый Linking result.
