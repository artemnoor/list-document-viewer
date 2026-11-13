# 28. Корректные JSON-пути evidence в Vue

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Сейчас.**

Корректные пути в исходном Extraction JSON; фильтрация и сортировка UI не меняют source index.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Построение пути через table.id и row.row_id подтверждено App.vue; массивы требуют индексов.

- [phystech-trace/frontend/src/App.vue](../../phystech-trace/frontend/src/App.vue) — selectField и template таблиц формируют tables.${table.id}.rows.${row.row_id}.${field}.
- [phystech-trace/services/document-linking/src/linking/evidence-validation.ts](../../phystech-trace/services/document-linking/src/linking/evidence-validation.ts) — Существующий resolveJsonPath задаёт совместимую грамматику путей.
- [phystech-trace/frontend/src/components/EvidencePanel.vue](../../phystech-trace/frontend/src/components/EvidencePanel.vue) — Панель отображает переданные значения и path, что само по себе не доказывает разрешимость пути.

## Причина и границы вывода

Стабильный ID объекта не равен индексу в массиве. Визуально правдоподобный evidence скрывает неверный адрес.

## Рекомендуемое решение

Использовать реальные tableIndex/rowIndex исходного immutable Extraction либо серверный locator с reference_id и точным path. ID остаётся идентификатором сущности; path — адресом в конкретной версии JSON.

## Последовательность будущего изменения

1. В renderer строить view model {artifact_id, table_id, row_id, source_path}; сохранить исходные индексы до фильтрации/сортировки.
2. Согласовать, path указывает на field object или его value; использовать существующую грамматику resolver и проверку raw_value, не менять всё произвольно на JSON Pointer.
3. Путь fields.${key} тоже должен поддерживать допустимые ключи с точками/скобками: либо канонический bracket escaping, либо реестр locators.
4. Перед открытием доказательства проверять artifact version, разрешение path и равенство исходного значения. При ошибке показывать диагностику, не подставлять похожую строку.

## Проверка исправления

- Два массива с произвольными ID, удалёнными/переупорядоченными строками, фильтром и сортировкой: каждый клик разрешается до того же поля.
- Ключ с точкой, нулевое значение, null и duplicate row label; historical extraction после нового run.

## Критерий закрытия

Все evidence paths разрешаются в указанном artifact и дают точные raw values. ID используется для Vue key, но не подменяет array index.

## Зависимости и ограничения

Связанные замечания: [№10](10-end-to-end-versioning.md), [№26](26-linking-input-coverage.md), [№27](27-contract-compatibility.md), [№30](30-xlsx-evidence-viewer.md), [№34](34-representative-e2e.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Использование индекса отображаемой, уже отсортированной таблицы также неверно; нужен индекс исходного JSON.

