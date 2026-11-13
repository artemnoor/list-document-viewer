# 23. Адрес сервера в Swagger Parser

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас.**

Исправить реальный servers.url Parser и проверить Swagger-запросы в поддерживаемых профилях.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Статически подтверждено: servers.url = http://localhost:18765 в отдаваемой Parser спецификации; Compose публикует её на 8081.

- [phystech-trace/services/document-parser/openapi.json](../../phystech-trace/services/document-parser/openapi.json) — Строка 8: servers указывает localhost:18765.
- [phystech-trace/docker-compose.yml](../../phystech-trace/docker-compose.yml) — document-parser: 127.0.0.1:8081:18765.
- [phystech-trace/services/document-linking/openapi.yaml](../../phystech-trace/services/document-linking/openapi.yaml) — Linking уже настроен на 8083; эту прежнюю претензию не повторять.
- [backend/server.py](../../backend/server.py) — Маршрут /openapi.json читает TRACE_SERVICE_DIR/openapi.json; это фактически используемая спецификация.

## Причина и границы вывода

Внутренний порт контейнера/standalone запуска не совпадает с адресом браузера пользователя. Простая замена localhost:18765 на localhost:8081 сломает иной профиль и reverse proxy.

## Рекомендуемое решение

Предпочесть относительный servers.url для той же origin, при необходимости с документированным proxy prefix. Абсолютные адреса оставлять явными deployment overrides.

## Последовательность будущего изменения

1. Изменять phystech-trace/services/document-parser/openapi.json, который отдаёт backend/server.py. Предпочесть относительный origin; проверить через HTTP в Compose и standalone.
2. Согласовать root_path/forwarded prefix с reverse proxy; доверять forwarded headers только от доверенного proxy.
3. Добавить contract/smoke проверку: Swagger Try it out отправляет запрос на доступный origin, а не на внутреннее имя/порт контейнера.

## Проверка исправления

- Compose на 8081, standalone на 18765 и внешний origin с prefix; проверить фактический request URL в браузере.
- У Linking сохранить правильный 8083 и service-to-service URL: внешний и внутренний адреса имеют разные назначения.

## Критерий закрытия

Запрос из Swagger работает во всех поддерживаемых профилях. Сохранены правильные внутренние адреса и внешний порт Linking 8083.

## Зависимости и ограничения

Связанные замечания: [№24](24-offline-swagger.md), [№25](25-openapi-conformance.md), [№35](35-integration-ci.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Нельзя подменить внутренний PARSER_URL Gateway внешним localhost:8081: localhost внутри контейнера указывает на сам контейнер.

