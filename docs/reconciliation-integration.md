# Требования Verification к Reconciliation

Контракт `reconciliation-result-1.0.0` остаётся предварительным. Verification не расширяет его обязательные поля и не вычисляет финансовый результат заново. Проверки ниже применяются к существующему объекту и совместимы с Extraction 1.2.0 и Linking 1.2.0.

## Идентификаторы и fingerprints

- `run_metadata.project_id` должен совпадать с `project_id` запроса.
- `run_metadata.calculation_id` связывает все targets одного расчёта; optional `calculation_id` в target/result/proof, если он передан, обязан совпадать.
- `input_data.extraction_id` и `extraction_schema_version` должны совпасть с переданным первичным Extraction.
- `input_data.extraction_hash` должен быть непустым и точно совпадать с `extraction.input_hash`.
- Для каждого supporting document, на который ссылается `used_sources`, `input_data.supporting_extraction_hashes[document_id]` должен совпадать с соответствующим Extraction `input_hash`.
- При использовании Linking передавайте `linking_run_id` и `linking_contract_version`, совпадающие с Linking result. В `input_documents` укажите те же `document_id`, `extraction_id`, `document_type`, `version`, `schema_version` и `input_hash`. Hash обязателен для автоматического подтверждения используемой связи.

Fingerprint должен быть вычислен владельцем immutable Extraction artifact. Не пересчитывайте его по отображаемому JSON в Gateway, если upstream задаёт иной алгоритм; передавайте без изменения исходный `input_hash`.

## Доказательства источников

Каждый `used_sources` item должен указывать стабильные `source_id`, `document_id`, `extraction_id`, точный JSON Pointer к wrapper `/value`, `row_id` при наличии, evidence status и связанные operation IDs. Ссылка должна разрешаться в переданном Extraction, соответствовать статусу extracted и иметь provenance с исходным locator. Неизвестные или неподтверждённые значения не входят в доказательство расчёта.

`system_validated` позволяет автоматическую проверку при совпадении всех ссылок и fingerprints. `human_confirmed` сохраняется отдельно как подтверждение специалиста. Само значение `status=confirmed` в Linking не доказывает правильность связи: Verification сверяет linked документы, input versions/hashes, path, raw value, row ID, conflicts и diagnostics. `verification_status=not_reviewed` не мешает автоматическому результату, когда техническая цепочка проходит эти проверки.

`excluded_sources` и unused documents остаются следом для аудита, но не считаются подтверждением expected value. Не включайте их ID в `operations[].input_source_ids`.

## Calculation trace

- У каждой used source ссылки должен быть хотя бы один `operation_id`, а каждая операция обязана перечислить те же `input_source_ids`.
- Operation IDs и source IDs должны быть уникальны внутри target.
- Если формула содержит явные source IDs, этот набор должен совпадать с `input_source_ids`. Для единственной вычислительной операции top-level `result.formula` должен совпадать с `operation.formula`.
- Operation output должен однозначно совпадать с `result.expected_value` с учётом объявленных value type/currency. Если ни один output или несколько outputs соответствуют expected value, Verification не подтверждает результат.
- Неподдерживаемый тип proof, неполный граф или формула, семантику которой нельзя связать с перечисленными inputs, остаются `needs_review`/unproven.

Verification намеренно не интерпретирует формулы как финансовую программу и не повторяет суммирование, VAT, округление или правила Reconciliation. Формат формального `calculation_proof` пока не стандартизован upstream; не отправляйте одноимённое поле как доказательство до совместного версионирования схемы и адаптера.

## Покрытие и статусы

Создайте target для каждого применимого показателя КФЗ. Отсутствующий target отображается как `insufficient_data`; target со `calculation_status=not_applicable` сохраняется, но не увеличивает verified coverage. Запуск с неполным охватом не может получить общий `matched` или `mismatch`. Проверяйте `completeness` и trust отдельно от `overall_status`.

При нарушении целостности Verification возвращает диагностику и не присваивает окончательный статус. Исправления контракта Reconciliation должны прийти как новая версия и отдельный adapter; текущая схема и adapter 1.0.0 сохраняются.
