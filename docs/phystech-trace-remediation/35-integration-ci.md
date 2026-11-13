# 35. CI общей интеграции

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас, поэтапно.**

Начать с unit, contract, build и mock E2E. Расширять CI постепенно; полноценный chaos/conformance/live automation не блокирует старт CI.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

В корне нет tracked .github/workflows; найден только вложенный workflow импортированного Linking.

- [phystech-trace/services/document-linking/.github/workflows/ci.yml](../../phystech-trace/services/document-linking/.github/workflows/ci.yml) — Вложенный workflow не запускается GitHub Actions как корневой.
- [phystech-trace/tests/contracts/test_contracts.py](../../phystech-trace/tests/contracts/test_contracts.py) — Существующая точка contract tests.
- [phystech-trace/tests/e2e/README.md](../../phystech-trace/tests/e2e/README.md) — Существующие E2E команды и ограничения.
- [phystech-trace/services/structured-extraction/package.json](../../phystech-trace/services/structured-extraction/package.json) — Unit/API scripts нужно различать со standalone runtime.

## Причина и границы вывода

Модульные проверки и сохранённый ручной отчёт не гарантируют совместимость очередного изменения Gateway/Compose/контрактов.

## Рекомендуемое решение

Первый root workflow: unit существующих модулей, pinned contract tests, сборки и Vue typecheck, затем mock E2E через настоящие API/БД. Работать без live secrets на PR. Compose smoke/recovery/conformance добавлять по мере готовности; live сначала остаётся управляемой отдельной проверкой.

## Последовательность будущего изменения

1. На push/PR запускать реальные package scripts/requirements с корректными working-directory и lockfiles; standalone runtime Extraction проверять отдельно от Cloudflare test:api.
2. Подключить mock только на границе LLM transport; не заменять алгоритмы Parser/Extraction/Linking. Изолировать CI volumes/project name и установить timeout/cleanup.
3. Не выдавать fork PR live ключи; сохранять безопасные отчёты. Required checks включать после реального успешного исполнения, не после одного создания YAML.

## Проверка исправления

- В чистом runner проходят unit/contracts/build/mock E2E; намеренная ошибка контракта или сборки делает pipeline красным.
- Mock E2E проверяет полный HTTP-путь, evidence и negative response; обязательный job не считается прошедшим при skip.

## Критерий приёмки MVP

Root workflow реально выполняет unit, contract, build и mock E2E на push/PR. Полные chaos/conformance/live jobs не являются условием начала CI.

## Что отложено

Автоматизированные Compose fault/recovery matrix, полный conformance suite и live workflow_dispatch с бюджетом — по мере развития. Ручной управляемый live приёмочный прогон №34 сохраняется.

Исходная расширенная проработка ниже сохранена как справочный вариант; она не расширяет текущий scope. При расхождении объёма приоритет имеют разделы MVP выше.

## Расширенный вариант для следующих этапов

Будущий root .github/workflows/integration.yml запускается на push/PR. Jobs: статические проверки и unit, сборки, HTTP contract suite, Compose smoke, mock LLM E2E, recovery subset и corpus policy. Live — отдельный управляемый workflow_dispatch с бюджетом и разрешёнными синтетическими данными.

## Расширенный вариант: возможные шаги

1. Составить команды из реальных package scripts/requirements: backend unittest, Extraction npm test, Linking npm test/build, Vue typecheck/build, shared contracts. Указывать working-directory и lockfile cache.
2. Compose в изолированной CI project namespace, тестовые уникальные credentials, mock provider adapter и bounded wait по readiness. Проверять standalone Extraction, не подменять его Cloudflare test:api.
3. PR checks работают без live secrets; fork PR не получает ключи. Live запускается из доверенной revision/environment, с max budget/time и без исполнения непроверенного PR-кода с секретами.
4. Сохранять только безопасные diagnostics, hashes и summaries; always cleanup. Отсутствие Docker/resources/dependency не считается успешным skip обязательного job.
5. Назначить required checks после первого успешного исполнения; единый агрегирующий job исключает ложный зелёный при path filters/пропущенной зависимости.

## Расширенный вариант: будущие проверки

- Позитивный pipeline на чистом runner; намеренно сломать schema, сборку, readiness, foreign-project ACL и coverage — нужные jobs красные.
- Проверить fork PR без secrets, отмену run, недоступный provider и ограничение live расходов.

## Критерий полного закрытия исходного замечания

Root workflow реально исполнен в GitHub, обязательные jobs проходят на PR/push; mock/live результаты явно различимы. Создание YAML без внешнего исполнения не закрывает замечание полностью.

## Зависимости и ограничения

Связанные замечания: [№14](14-recovery-fault-injection.md), [№17](17-gateway-liveness-readiness.md), [№18](18-worker-health.md), [№19](19-production-secrets.md), [№22](22-tracked-document-audit.md), [№25](25-openapi-conformance.md), [№27](27-contract-compatibility.md), [№33](33-independent-quality-benchmark.md), [№34](34-representative-e2e.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

CI pipeline и mock-provider transport ещё предстоит реализовать. В этой работе ни workflow, ни настройки branch protection не изменялись.

