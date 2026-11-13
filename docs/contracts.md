# Контракты и совместимость

## Зафиксированные upstream источники

Исследованы и зафиксированы 13 ноября 2026 года:

| Репозиторий | Ветка/версия | Commit SHA | Используемый артефакт |
| --- | --- | --- | --- |
| [list-document-viewer](https://github.com/artemnoor/list-document-viewer/tree/feat/phystech-trace-integration) | `feat/phystech-trace-integration` | `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf` | `phystech-trace/contracts/structured-extraction-1.2.0.schema.json`, `document-linking-1.2.0.schema.json`; документы и fixtures Linking |
| [kfz-structured-extraction-](https://github.com/artemnoor/kfz-structured-extraction-) | HEAD | `1e922e284805f2c1b343b4cb369813c8073b67dd` | Extraction output `schema_version=1.2.0`; SHA совпадает с источником, указанным integrated `contracts/versions.json` |
| [kfz-document-linking](https://github.com/artemnoor/kfz-document-linking) | HEAD | `28a3662cc0597093ad6264f70f591db19c37e061` | Linking output `contract_version=1.2.0`; source SHA указан в integrated `contracts/versions.json` |

В upstream `contracts/versions.json` Extraction закреплён как `1.2.0`, Linking output — `1.2.0`. Схемы сохранены без модификации в `schemas/upstream/`. Fixtures Extraction скопированы без преобразования в `fixtures/upstream-structured-extraction-1.2.0/`.

## Проверенная структура

Extraction требует `extraction_id`, `document_id`, `version`, `schema_version`, `extracted_at`, `classification`, `extraction_engine`, `mode`, `fields`, `tables`, `indicators`, `missing_fields`, `review_required`, `document_type` и type-specific `line_items` либо `payment_schedule`. Значения передаются в wrapper-объектах с `value`, `source_value`, `status`, `confidence`, `provenance`; строки имеют `row_id` и отдельные wrappers для quantity/amount. PDF locator содержит `page_no`, `bbox`, `coordinate_origin`, `page_size`; XLSX — `sheet_name`, `cell_address`, `source_ref`.

Linking 1.2.0 содержит `input_documents`, `links`, `review_required`, `unlinked_documents`, `link_validation_diagnostics`, `analysis_summary` и `processing_metadata`. `input_documents` сохраняет extraction ID, версию, schema version, input version и, когда есть, input hash. Link содержит `link_id`, relationship, endpoints, строки, evidence, confidence, `status`, `verification_status`, conflicts. `confirmed` с `verification_status=not_reviewed` не считается human confirmation.

## Найденное upstream-несоответствие

`phystech-trace/services/document-linking/examples/linking-result.json` в зафиксированном integrated commit заявляет `contract_version=1.0.0` и не содержит обязательные для опубликованной 1.2.0-схемы `analysis_summary` и `link_validation_diagnostics`; отдельные link поля также не совпадают со схемой. Файл сохранён без изменений как `fixtures/upstream-linking/linking-result-legacy-1.0.0.json`. Он ожидаемо отклоняется с точной версией/схемой и не преобразуется молча. Это upstream sample, а не валидный Link 1.2.0 результат.

Из-за этого нет возможности честно показать принятый реальный upstream Link 1.2.0 output fixture: в исходном сервисе найденный output example относится к 1.0.0. Контрактные сценарии используют минимальный Link 1.2.0 snapshot, соответствующий опубликованной схеме, и настоящие Extraction 1.2.0 fixtures.

## Контракт Reconciliation Engine 1.0.0

Вход: `contract_version=1.0.0`, `extraction_results[]`, исходный `linking_result`, `context.targets[]`, период, правила допустимой передачи данных и необязательные `prior_decisions[]`. Полная JSON Schema запроса — `schemas/reconciliation-request-1.0.0.schema.json`; она встраивает upstream Extraction/Linking схемы. Подтверждённое человеком решение содержит reviewer, время, расчётный план и явные `accepted_fact_ids`/`accepted_link_ids`. Оно может снять ручную проверку конкретного Extraction `review` или Linking edge; `missing` значения не превращаются в числа.

Выходной формат закреплён отдельно от кода в `schemas/reconciliation-result-1.0.0.schema.json`. Этот же объект возвращают `POST /api/v1/reconciliations` и `GET /api/v1/reconciliations/{reconciliation_id}`; OpenAPI описывает endpoints, а JSON Schema остаётся нормативным контрактом для независимых потребителей. Contract tests читают JSON Schema и пример напрямую, независимо от Pydantic-моделей реализации.

### Поля на каждый целевой показатель

- `target.target_id` — стабильный ID показателя; `target.kfz_origin` — обязательные `document_id`, `extraction_id`, `fact_id` и точный JSON Pointer `source_path` к wrapper показателя в Extraction. `source_ref` — исходный locator документа, если upstream его предоставил. Невалидный или отсутствующий locator отклоняется до расчёта.
- `expected_value` и `exact_value_before_rounding` — decimal-строки либо `null`; `currency` и `unit` передаются отдельными полями и могут быть `null`, если единица неизвестна. Значение никогда не кодируется JSON float.
- `period` всегда содержит `start`, `end` и `basis`. Границы периода каждая могут быть `null`, если неизвестны. `amount_basis` сообщает `gross`, `net` или `unspecified`.
- `formula` всегда присутствует: строка, если план сформирован, иначе `null`. `formula_status` различает `executed`, `proposed` и `not_available`.
- `used_sources` перечисляет только факты, реально использованные в опубликованном расчёте. `excluded_sources` содержит доступные, но не использованные кандидаты и причины исключения. Источник несёт ID документа/извлечения/факта, JSON Pointer, статус, hash и provenance. Upstream provenance может быть `null`, если его не было; JSON Pointer и hash факта остаются обязательными.
- `completeness_status`, `uncertainty_status`, `errors`, `information_gaps`, `assumptions` и `provenance` обязательны. Provenance фиксирует hash всего снимка, целевой locator и списки ID использованных/исключённых фактов.

### Статусы и nullability

`status` — `calculated`, `insufficient_data` или `manual_review`. При `calculated` обязательно: `completeness_status=complete`, `uncertainty_status=none`, decimal `expected_value`, выполненная формула, отсутствие errors/gaps/assumptions, `rounding.applied=true` и `manual_review_required=false`. Для `insufficient_data` значение и точное значение равны `null`, completeness и uncertainty — `unknown`, округление не применено. Для `manual_review` оба значения также `null`, uncertainty — `present`, completeness — `partial` или `unknown`; формула может быть только предложенной. Расчёт, которому нужны уточнение, допущение или разрешение ошибки, не публикуется как подтверждённый `expected_value`.

Неизвестные `currency`, `unit` и границы периода передаются как явный `null`, а не опускаются. Путь к целевому КФЗ-показателю, ID исходных Extraction и Linking, их версии и hash не nullable. Отсутствующая upstream provenance допускает `null`, при этом источник всё равно трассируется по JSON Pointer и input hash.

### Знаки и округление

Суммы хранятся десятичными строками и сохраняют знак из исходного Extraction. `sum` складывает signed values алгебраически; вычитание выполняется только явным шагом `subtract`. Движок не применяет `abs` и не выводит смысл отрицательной суммы без evidence. Вычисления используют `Decimal` с рабочей точностью 38 значащих цифр; промежуточные значения не округляются, кроме явного шага `round`. Финальный `expected_value` округляется один раз до указанного `rounding.scale` методом `ROUND_HALF_UP`. `exact_value_before_rounding` сохраняет результат до этого финального округления. Масштаб — целое от 0 до 8.

На уровне запуска `input_snapshot` содержит `document_id`, `extraction_id`, версию и schema version каждого Extraction, а также `linking_run_id`, `linking_contract_version` и hash Linking-входа. `comparison_performed=false` и `reliability_conclusion=null` фиксируют, что Reconciliation не сравнивает значение с КФЗ и не делает вывод о надёжности.
# Совместимые расширения и snapshot binding

Для `prior_decisions` сохранён формат Reconciliation `1.0.0`; поля привязки к snapshot добавлены как необязательное расширение. Движок принимает решение к исполнению только при совпадении `snapshot_sha256`, `linking_sha256`, карт версий Extraction, хешей выбранных фактов и итогового `decision_sha256`. Старые неприкреплённые решения остаются читаемыми, но возвращают диагностику `stale_human_decision` и не исполняются.

В целевом индикаторе допускается необязательный `economic_measure` (`planned`, `actual`, `accrued`, `paid`, `unspecified`). В источниках результата это поле также необязательно. Для результата изолированного сбоя цели поля происхождения цели могут быть `null`; остальные поля результата сохраняют контракт `1.0.0`.

Перед расчётом проверяются версии Linking и Extraction, идентификаторы/версии документов, а при наличии upstream hash — его совпадение с соответствующим Extraction. Версия Linking 1.0.0 не адаптируется молча к 1.2.0: API возвращает диагностику контракта.
