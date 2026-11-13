# 10. Сквозные версии Parser → Extraction → Linking

[Общий индекс](00-index.md) · 🔴 Критично

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас, упрощённо.**

Immutable inputs, hashes и manifest обязательны; отдельное артефактное хранилище и сложная модель сущностей не обязательны.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Константа input_version = 1 подтверждена; hash Parser JSON уже хранится и должен быть сохранён.

- [phystech-trace/services/structured-extraction/runtime/server.mjs](../../phystech-trace/services/structured-extraction/runtime/server.mjs) — inputHash вычисляется из parserResult; result.input_version = 1; сохранённая version выделяется отдельно.
- [phystech-trace/gateway/main.py](../../phystech-trace/gateway/main.py) — Linking Idempotency-Key построен из document_id/extraction_id, но полного manifest и версий policy/engine нет.

## Причина и границы вывода

input_version и версия результата описывают разные сущности. Не хватает идентификатора upstream artifact и полного набора вычислительных зависимостей.

## Рекомендуемое решение

Хранить неизменяемый снимок входа каждого run в PostgreSQL/существующем файловом хранении. Минимум: source_hash, hash и snapshot Parser JSON, extraction_id/version/hash, input_revision, manifest_hash и revisions конфигурации. Новые вычисления создают новые записи; старый payload не обновляется по latest.

## Последовательность будущего изменения

1. Определить стабильный hash JSON отдельно от hash исходных байтов. Фиксировать точные source bytes либо гарантированно неизменяемую ссылку на них.
2. Добавить минимальный run record/snapshot с полным составом документов, ролями и версиями результатов. Из него строить Linking input, idempotency и resume.
3. Публиковать current result только при совпадении manifest и current revision. Evidence ссылается на сохранённый snapshot версии; legacy_unknown не заменяется выдуманной версией 1.

## Проверка исправления

- Те же байты/иной порядок JSON-ключей; другой OCR/model/settings; повторная Extraction с сохранением старого payload.
- Историческое evidence разрешается после нового run; несовпадение manifest запрещает resume и current publication.

## Критерий приёмки MVP

Каждый run воспроизводимо привязан к неизменяемым входам и версиям, а старые результаты не перезаписываются. Отдельная подсистема хранения не является prerequisite.

## Что отложено

Нормализованный registry всех artifacts, content-addressed object storage и перенос крупных payload из БД — при измеренной необходимости.

Исходная расширенная проработка ниже сохранена как справочный вариант; она не расширяет текущий scope. При расхождении объёма приоритет имеют разделы MVP выше.

## Расширенный вариант для следующих этапов

Сохранить исходный source_hash SHA-256 байтов, immutable parser_artifact_id/hash и его revision, extraction_id/version/input_artifact_hash, linking run manifest. Версию схемы и версию данных хранить раздельно. Все proposed поля — новый дизайн, не описание уже существующего контракта.

## Расширенный вариант: возможные шаги

1. Определить canonical JSON для artifact hash; hash байтов файла считать отдельно. Порядок ключей JSON не должен создавать новую семантическую версию.
2. Manifest включает project_document_id, роль, source/parser/extraction hashes, schema/engine/model/prompt/settings/policy revisions. Его hash служит ключом resume и current-check.
3. Input_version берётся из upstream artifact, result version — из атомарного счётчика; каждый evidence locator привязан к artifact, а не mutable latest.
4. Старые записи маркировать legacy_unknown при отсутствии исходной версии; не проставлять достоверную 1 задним числом.

## Расширенный вариант: будущие проверки

- Одинаковые байты и другой порядок JSON-ключей; те же байты с новой OCR-моделью/настройкой; новые байты того же имени.
- Разрешить evidence исторической связи после нескольких повторных Extraction и отзыва согласия.

## Критерий полного закрытия исходного замечания

Для любого результата восстанавливаются точные байты, upstream artifacts и конфигурация. Reuse/resume разрешён только при совпадении зависимостей.

## Зависимости и ограничения

Связанные замечания: [№8](08-project-isolation.md), [№11](11-atomic-extraction-versions.md), [№20](20-database-migrations.md), [№27](27-contract-compatibility.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Нельзя заменить существующее поле без проверки pinned контрактов 1.2.0; использовать совместимое расширение/envelope или новую версию с адаптером.

