# 25. Соответствие OpenAPI фактическому API

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас, базовые smoke-тесты.**

Проверить основные реальные HTTP-маршруты, ответы и ошибки. Полный conformance/fuzz suite позже.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Статические спецификации и маршруты имеют отдельные источники; полное расхождение всех endpoints не доказано.

- [phystech-trace/services/structured-extraction/runtime/openapi.json](../../phystech-trace/services/structured-extraction/runtime/openapi.json) — Standalone API имеет отдельную спецификацию.
- [phystech-trace/services/structured-extraction/runtime/server.mjs](../../phystech-trace/services/structured-extraction/runtime/server.mjs) — Фактические ветви method/path/status.
- [phystech-trace/tests/contracts/test_contracts.py](../../phystech-trace/tests/contracts/test_contracts.py) — Семь тестов проверяют data contracts, но не полную HTTP-поверхность.
- [phystech-trace/gateway/main.py](../../phystech-trace/gateway/main.py) — FastAPI уже может генерировать OpenAPI; нужны типизированные response models.

## Причина и границы вывода

Синтаксически корректная спецификация не гарантирует совпадение ошибок, status codes, auth, content types и лимитов с сервером.

## Рекомендуемое решение

Добавить компактные HTTP smoke-тесты фактически запущенных сервисов: основные операции Gateway/Parser/Extraction/Linking, ожидаемые status/content type, минимальная схема и типовые ошибки. Сохранить существующие shared-schema tests. Перестройка всех маршрутов в единый реестр пока не нужна.

## Последовательность будущего изменения

1. Составить небольшой route inventory основного конвейера и сверить его со статическими спецификациями.
2. Проверять create/upload/process/status/results, source/page, review и auth failures; добавить 400/403/404/422 и health readiness там, где они предусмотрены контрактом.
3. Запускать на standalone Extraction runtime и реальных HTTP API в CI, не подменять их импортированным Cloudflare API.

## Проверка исправления

- Успешные ответы и основные отказные случаи валидируются против OpenAPI/shared contracts.
- Исходный файл/page response проверяется как binary content, JSON ошибки — как error envelope.

## Критерий приёмки MVP

Основные маршруты конвейера и типовые ошибки проверяются исполняемыми smoke-тестами; полное доказательство соответствия всей API-поверхности пока не заявляется.

## Что отложено

Полный двусторонний conformance suite, генерация route registry/client, breaking-change анализ и property-based/fuzz проверки — следующим этапом.

Исходная расширенная проработка ниже сохранена как справочный вариант; она не расширяет текущий scope. При расхождении объёма приоритет имеют разделы MVP выше.

## Расширенный вариант для следующих этапов

Завести route inventory и executable contract suite. Для FastAPI генерировать схемы из моделей; для Node выбрать единый реестр маршрутов/схем либо поддерживать статическую спецификацию с обязательными двусторонними проверками.

## Расширенный вариант: возможные шаги

1. Инвентаризировать все маршруты, включая source bytes/pages, pagination/history, jobs/resume/review, auth и health. Обе стороны проверяют отсутствие незадокументированных операций.
2. Проверять request/response schema, required headers, security, 4xx/5xx, binary content type, ограничения payload и error envelope.
3. Применять data schema из shared contracts без ручных копий; OpenAPI dialect и validator должны совпадать.
4. В CI сравнивать спецификацию с baseline и классифицировать breaking changes; генерация клиентов — дополнительная проверка, не доказательство исполнения.

## Расширенный вариант: будущие проверки

- Позитивный и негативный запрос на каждую operation; реальные startup/runtime, неправильный тип и неверный enum.
- Скачать исходный XLSX/PDF и page image: проверить байты/headers, не пытаться валидировать их как JSON.

## Критерий полного закрытия исходного замечания

В CI обнаруживается добавленный/удалённый маршрут и изменённый реальный ответ, ошибка или auth requirement.

## Зависимости и ограничения

Связанные замечания: [№4](04-gateway-authorization.md), [№5](05-extraction-trust-boundary.md), [№23](23-parser-swagger-server.md), [№24](24-offline-swagger.md), [№27](27-contract-compatibility.md), [№35](35-integration-ci.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Автогенерация без response models оставляет ответы неточными; property-based тесты должны работать на изолированных синтетических данных.

