# 15. Восстановление повреждённых ответов LLM

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас.**

Структурированные ошибки, ограниченные повторы повреждённой части, строгая проверка evidence и сохранение валидных checkpoints.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Неуспешные ответы подтверждены; retries, checkpoints и evidence correction уже реализованы.

- [phystech-trace/services/document-linking/src/linking/llm-matcher.ts](../../phystech-trace/services/document-linking/src/linking/llm-matcher.ts) — requestModel, completed_fragments, maxEvidenceCorrectionAttempts и проверки exact references.
- [phystech-trace/services/document-linking/src/linking/polza-client.ts](../../phystech-trace/services/document-linking/src/linking/polza-client.ts) — Транспорт, ошибки и JSON-ответ провайдера.
- [phystech-trace/services/document-linking/server/worker.ts](../../phystech-trace/services/document-linking/server/worker.ts) — Классификация retryable ошибок и backoff.

## Причина и границы вывода

Повтор того же слишком большого запроса не устраняет truncation; исправление evidence не равно восстановлению синтаксически повреждённого fragment response.

## Рекомендуемое решение

Разделить транспорт, JSON parsing, JSON Schema, ссылки/значения и предметную согласованность. Каждый дефект имеет ограниченный recovery, общий бюджет проекта и привязку к chunk/input hash.

## Последовательность будущего изменения

1. При усечении по output limit уменьшить чанк/увеличить допустимый output в рамках preflight; JSON mode/schema использовать только после проверки capabilities.
2. Допускать лишь безопасное снятие обёртки markdown; не угадывать отсутствующие числа и не собирать ответ из произвольных обломков JSON.
3. При schema/reference ошибке передать diagnostics и исходные допустимые reference IDs, повторить повреждённую часть. Валидные части сохранять в checkpoint только после полной проверки.
4. Отдельно обрабатывать 429/5xx, 401/403, budget exceeded, cancellation; ошибки политики не ретраить. Проверять дубли и противоречия после merge.

## Проверка исправления

- Усечённый JSON, неверный тип, лишний документ, корректный ID с подменённым raw_value, обрыв stream.
- Recovery последнего чанка не вызывает обработку всех предыдущих; исчерпание попыток создаёт partial/failed с coverage.

## Критерий закрытия

Повреждённая часть либо восстановлена до строгого валидного результата, либо явно не обработана. Никакой repair не создаёт источник доказательства.

## Зависимости и ограничения

Связанные замечания: [№1](01-linking-full-set.md), [№10](10-end-to-end-versioning.md), [№14](14-recovery-fault-injection.md), [№16](16-project-budgets-cancellation.md), [№26](26-linking-input-coverage.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Молчаливое удаление неудобных связей может дать валидный, но неполный граф; учитывать rejected proposals в диагностике.

