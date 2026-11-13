# 27. Обратная совместимость контрактов

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас.**

Сохранить pinned версии и обратную совместимость существующих модулей, включая round-trip provenance и сложных структур.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Есть pinned schemas и fixtures; матрицы версий и полного round-trip сложных данных нет.

- [phystech-trace/tests/contracts/test_contracts.py](../../phystech-trace/tests/contracts/test_contracts.py) — Проверяются схемы, pinned registry и часть XLSX metadata.
- [phystech-trace/contracts/versions.json](../../phystech-trace/contracts/versions.json) — Текущие версии и source commits.
- [phystech-trace/services/document-linking/fixtures/upstream-structured-extraction-1.2.0](../../phystech-trace/services/document-linking/fixtures/upstream-structured-extraction-1.2.0) — Существующие upstream examples.

## Причина и границы вывода

Совпадение файла schema с pinned source фиксирует одну версию, но не поведение producer/consumer после обновления или преобразования данных.

## Рекомендуемое решение

Определить поддерживаемую матрицу producer/consumer N и N−1, semver policy и правила расширений. Raw upstream payload сохранять неизменным, а typed view допускает только согласованные поля; если схема запрещает extras, использовать согласованный extension envelope.

## Последовательность будущего изменения

1. Зафиксировать backward/forward compatibility для optional/required fields, enums, nullable и новых статусов. Breaking schema требует новой версии и adapter.
2. Добавить golden fixtures со sparse arrays, merged ranges, formulas/cached values, null/empty/zero, bbox origin/page size, вложенными таблицами и неизвестными extension fields.
3. Проверять round-trip upload → storage → read → Linking: неизвестные разрешённые данные не теряются через object reconstruction, coercion или normalizer.
4. Evidence paths связывать с immutable original extraction; адаптер не должен незаметно менять индексы и смысл путей.

## Проверка исправления

- Старый consumer получает разрешённое новое поле; новый consumer читает сохранённый старый artifact.
- Неподдерживаемая версия явно отклоняется; координаты, merged cells и raw значения сохраняются после полного round-trip.

## Критерий закрытия

CI проверяет объявленную матрицу версий и ловит потерю metadata/unknown fields. Стратегия новых versioning полей №10 совместима с этой матрицей.

## Зависимости и ограничения

Связанные замечания: [№10](10-end-to-end-versioning.md), [№20](20-database-migrations.md), [№25](25-openapi-conformance.md), [№28](28-evidence-json-paths.md), [№35](35-integration-ci.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Требование сохранять неизвестное не означает разрешить любые поля в закрытой schema; сначала согласовать правила extensions.

