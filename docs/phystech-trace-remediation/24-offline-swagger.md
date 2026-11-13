# 24. Swagger UI без внешнего CDN

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас, если нужен offline demo.**

Локальные Swagger assets обязательны для заявленного offline demo; без такого требования не блокируют следующий локальный MVP.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

unpkg.com подтверждён в standalone Extraction и Linking app.

- [phystech-trace/services/structured-extraction/runtime/server.mjs](../../phystech-trace/services/structured-extraction/runtime/server.mjs) — swaggerHtml загружает swagger-ui-dist@5 через unpkg.
- [phystech-trace/services/document-linking/server/app.ts](../../phystech-trace/services/document-linking/server/app.ts) — HTML документации с внешними Swagger UI assets.
- [phystech-trace/services/structured-extraction/Dockerfile](../../phystech-trace/services/structured-extraction/Dockerfile) — Точка включения assets в standalone образ.
- [backend/server.py](../../backend/server.py) — Дополнительное наблюдение: Parser SWAGGER_HTML также использует unpkg.com; включить в общую offline-проверку.

## Причина и границы вывода

Сервис работает локально, но браузер зависит от доступа к CDN. Диапазон @5 также не фиксирует точную версию ресурса.

## Рекомендуемое решение

Включить точную закреплённую версию swagger-ui-dist в lockfile и собранный образ; JS/CSS обслуживать локальными static routes. Проверять реально исполняемые standalone runtimes, а не только импортированный frontend.

## Последовательность будущего изменения

1. Проверить license/lockfile, копирование assets в final image и правильный content-type. Документация не должна требовать Node dev dependencies на runtime.
2. Заменить CDN URL локальными относительными ссылками, учесть proxy prefix; ограничить CSP и устранить внешние fonts/images/validator requests.
3. Согласовать доступ к docs/spec с моделью авторизации: документация не даёт обход ACL, а Try it out поддерживает нужную схему токена.
4. Применить тот же подход к Parser Swagger HTML, где выявлена такая же зависимость; не объявлять всю документацию автономной после исправления только двух сервисов.

## Проверка исправления

- Запретить внешний интернет браузеру и контейнеру после сборки: /docs, /openapi.json и assets загружаются.
- Playwright ловит запросы к внешним origin; Swagger выполняет разрешённый API-запрос при prefix deployment.

## Критерий закрытия

Документация полностью доступна offline в собранном образе; сеть CDN не нужна для просмотра и выполнения запросов.

## Зависимости и ограничения

Связанные замечания: [№19](19-production-secrets.md), [№23](23-parser-swagger-server.md), [№25](25-openapi-conformance.md), [№35](35-integration-ci.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Offline runtime не означает offline build: если нужен полностью автономный build, отдельно подготовить утверждённый package registry/cache.

