# 34. Репрезентативные сквозные сценарии

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас.**

Полный комплект и репрезентативные положительные, отрицательные и неоднозначные E2E — критерий готовности.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Компактный live E2E успешен на одной общей строке; широкий набор не завершает Linking.

- [phystech-trace/tests/e2e/run_e2e.py](../../phystech-trace/tests/e2e/run_e2e.py) — Текущие compact-linking и full-set profiles.
- [phystech-trace/tests/e2e/results/latest-run.json](../../phystech-trace/tests/e2e/results/latest-run.json) — Успешный компактный прогон и evidence.
- [phystech-trace/tests/e2e/review_decisions.py](../../phystech-trace/tests/e2e/review_decisions.py) — Проверка сохранения экспертного решения уже есть.
- [backend/tests/complex_fixtures/README.md](../../backend/tests/complex_fixtures/README.md) — Доступны сложные Parser fixtures для повторного использования.

## Причина и границы вывода

Один простой положительный случай не проверяет многозначность, полноту, качество и сбои. Mock и live отвечают на разные вопросы.

## Рекомендуемое решение

Разделить три набора: быстрый сквозной mock-provider через реальные HTTP/БД; контрактно-структурный корпус; управляемый live E2E с реальной моделью и budget. Mock заменяет только provider transport, не Parser/Extraction/Linking/Gateway.

## Последовательность будущего изменения

1. Добавить много договоров/строк, повторяющиеся суммы, один контрагент с разными операциями, косвенную связь, противоречие, missing document, полностью несвязанный комплект.
2. Включить PDF/OCR, XLSX merged/formula/sparse, DOCX nested tables и большие межчанковые строки; использовать синтетические или явно разрешённые материалы.
3. В каждом сценарии проверять manifest/coverage, точные links/rows/evidence, отсутствие лишних связей, source bytes и ожидаемый human-review статус.
4. Для MVP добавить сценарии upload во время run, базовый restart, остановку/лимиты вызовов-времени-токенов, чужой проект и stale results. Confidential internal-provider E2E активируется при реализации №12 перед конфиденциальным пилотом; сейчас проверить только безопасный blocked без внешней передачи. Полный chaos/денежный ledger не prerequisite. LLM-required профиль не принимает rules_only fallback.

## Проверка исправления

- Запуск с чистой БД и повтор с сохранёнными volumes; сравнение expected semantics и persistence.
- Negative mock ответы с выдуманным evidence обязательно приводят к контролируемому отклонению; live результат сравнивается с gold, не с самим собой.

## Критерий закрытия

Каждый риск имеет именованный воспроизводимый сценарий с assertions, hashes и отчётом. Компактный smoke остаётся быстрым тестом, но не единственным доказательством.

## Зависимости и ограничения

Связанные замечания: [№1](01-linking-full-set.md), [№3](03-llm-extraction.md), [№6](06-result-invalidation.md), [№7](07-uploads-during-processing.md), [№9](09-parser-quality-gate.md), [№10](10-end-to-end-versioning.md), [№12](12-confidential-linking-provider.md), [№14](14-recovery-fault-injection.md), [№28](28-evidence-json-paths.md), [№32](32-human-review-status.md), [№33](33-independent-quality-benchmark.md), [№35](35-integration-ci.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Не фиксировать полный текст LLM-ответа как golden: он нестабилен. Фиксировать проверяемые семантические ожидания и точные ссылки.

