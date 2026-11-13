# 26. Проверка полноты входа Linking

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас.**

Полный manifest/coverage; отдельно различать отсутствие связи, исключение и необработанный элемент.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Gateway проверяет отсутствие чужих input_documents; равенство множеств и покрытие строк не проверяются.

- [phystech-trace/gateway/main.py](../../phystech-trace/gateway/main.py) — Проверка any(item.document_id not in project docs) перед completed.
- [phystech-trace/services/document-linking/src/linking/llm-matcher.ts](../../phystech-trace/services/document-linking/src/linking/llm-matcher.ts) — reference_ids и completed_fragments уже помогают проверять фрагменты, но не доказывают правильность отношений.
- [phystech-trace/services/document-linking/src/linking/evidence-registry.ts](../../phystech-trace/services/document-linking/src/linking/evidence-registry.ts) — Реестр точных источников можно использовать для coverage.

## Причина и границы вывода

Допустимость каждого перечисленного ID не доказывает, что ничего не пропущено. unlinked_documents не должно смешивать «просмотрено, связи нет» и «не обработано».

## Рекомендуемое решение

Из immutable manifest сервер формирует ожидаемые документы/таблицы/строки/обязательные references. Coverage ledger создаётся оркестратором, а не свободным заявлением модели; хранит processed, excluded_by_policy, review_required, failed и причину.

## Последовательность будущего изменения

1. Проверять точное равенство входных IDs+artifact hashes, отсутствие дублей и extras. Missing element не заменять пустым результатом.
2. Для чанков валидировать expected references и связывать checkpoint с manifest hash; при повторе считать coverage идемпотентно.
3. Разделить processing coverage, candidate search coverage и semantic recall. Обработанная строка может иметь ноль связей, это не обязательно ошибка.
4. Публиковать completed только по согласованной policy допуска; ограниченный результат явно отображать как partial/limited.

## Проверка исправления

- Модель пропускает документ, дублирует ID, сообщает старую версию или не учитывает последнюю строку — валидация выявляет это.
- Полный отрицательный набор даёт 100% processing coverage и ноль связей; это допускается, если gold тоже отрицательный.

## Критерий закрытия

Каждый ожидаемый элемент имеет состояние и причину. Полнота обработки машинно проверяется; смысловая полнота измеряется отдельно по независимому gold.

## Зависимости и ограничения

Связанные замечания: [№1](01-linking-full-set.md), [№9](09-parser-quality-gate.md), [№10](10-end-to-end-versioning.md), [№15](15-llm-response-recovery.md), [№33](33-independent-quality-benchmark.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Даже возврат всех reference_ids моделью не доказывает, что она поняла элементы; не выдавать технический coverage за recall.

