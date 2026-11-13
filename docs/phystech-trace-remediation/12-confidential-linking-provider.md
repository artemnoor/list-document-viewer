# 12. Полный конвейер для конфиденциальных комплектов

[Общий индекс](00-index.md) · 🔴 Критично

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Позже, до конфиденциального пилота.**

Локальный MVP работает только с разрешёнными тестовыми данными. Для confidential сохранить blocked без внешнего fallback. Перед confidential-пилотом обязателен реальный внутренний E2E.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Архитектурное ограничение подтверждено внешним Polza-путём и Gateway policy.

- [phystech-trace/gateway/main.py](../../phystech-trace/gateway/main.py) — process_project и retry блокируют Linking для confidential/без внешнего согласия.
- [phystech-trace/services/document-linking/server/worker.ts](../../phystech-trace/services/document-linking/server/worker.ts) — Worker передаёт apiKey и модель в analyzeDocumentSet; текущий путь ориентирован на Polza.
- [phystech-trace/services/document-linking/src/linking/polza-client.ts](../../phystech-trace/services/document-linking/src/linking/polza-client.ts) — Текущий внешний транспорт.

## Причина и границы вывода

Внешний provider и политика допуска связаны так, что запрет внешней передачи блокирует всю функцию. Это корректный отказ по безопасности, но неполный продуктовый путь.

## Рекомендуемое решение

Ввести provider interface с capabilities: structured output, limits, usage, cancellation, model revision, trust zone. Разрешённый внутренний/локальный inference выбирается доверенной policy проекта; формат Linking и строгая evidence validation сохраняются.

## Последовательность будущего изменения

1. Сначала измерить требования к памяти, задержке и качеству на разрешённом корпусе; конкретная модель/железо ещё не выбраны.
2. Отделить transport adapter от prompting/chunking и метаданных Polza. Gateway разрешает confidential при доступном утверждённом внутреннем provider.
3. Разрешать только allowlisted внутренние адреса; не принимать произвольный base_url пользователя. Исключить внешний fallback, внешнюю telemetry и утечку через logs.
4. Preflight проверяет capability и готовность модели до OCR/долгого запуска; неподходящий provider даёт диагностируемый blocked.

## Проверка исправления

- Confidential PDF/XLSX/DOCX проходит полный конвейер при сетевом egress deny и сохраняет доказательства.
- Недоступная внутренняя модель не переключается на Polza; подменённый provider URL отклоняется; качество сравнивается по №33.

## Критерий закрытия

Есть реально успешный confidential E2E с утверждённым внутренним provider и нулевой внешней передачей. Один интерфейс провайдеров без такого прогона замечание не закрывает.

## Зависимости и ограничения

Связанные замечания: [№1](01-linking-full-set.md), [№3](03-llm-extraction.md), [№5](05-extraction-trust-boundary.md), [№16](16-project-budgets-cancellation.md), [№33](33-independent-quality-benchmark.md), [№34](34-representative-e2e.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

OpenAI-compatible HTTP API не гарантирует поддержку схемы и достаточное качество. Локальность сама по себе не делает модель точной.

