# Отчёт об устранении дефектов

**Проект:** Phystech Trace — Verification Engine 1.1.0
**Дата проверок:** 13 ноября 2026
**Область:** локальный Verification Engine и его границы с Extraction 1.2.0, Linking 1.2.0 и предварительным Reconciliation 1.0.0.

## Исправленные проблемы

### Статусы сравнения и полнота

- **Причина:** принятый допуск мог выглядеть как доказанное денежное расхождение; агрегированный `matched` мог скрыть непроверенные показатели и `not_applicable`; период мог браться из Reconciliation или контекста вместо Extraction.
- **Изменённые файлы:** `app/engine.py`, `app/models.py`, `app/explanations.py`, `docs/verification-logic.md`, `contracts/verification-result-1.1.0.schema.json`.
- **Исправление:** принятие по явному допуску хранит разницу и основание без установленной ошибки; добавлена полнота проверки; фактический период читается из Extraction; невозможность доказать результат отделена от `matched`/`mismatch`.
- **Проверки:** `test_tolerance_acceptance_never_claims_a_proven_amount_difference`, `test_aggregate_status_exposes_not_applicable_coverage_instead_of_matched`, `test_actual_period_comes_from_extraction_not_reconciliation_or_context`, `test_partial_multi_document_calculation_cannot_be_a_mismatch`.
- **Результат:** все четыре регрессии проходят в полном наборе.

### Доверие к источникам и связям

- **Причина:** одной метки Linking `status=confirmed` недостаточно для доказательства, а обязательное ручное подтверждение блокировало корректную автоматическую проверку.
- **Изменённые файлы:** `app/evidence.py`, `app/engine.py`, `app/models.py`, `tests/test_verification_scenarios.py`.
- **Исправление:** контракт результата отдельно отражает техническую валидность, автоматическое подтверждение Link, ручное подтверждение и достоверность расчёта. Проверяются документы, input hashes и версии, JSON Pointer, исходное значение, provenance и оба endpoint каждой использованной Link evidence.
- **Проверки:** `test_system_validated_source_can_support_automatic_result`, `test_confirmed_link_status_without_matching_evidence_is_not_accepted`, `test_confirmed_link_does_not_accept_forged_target_endpoint`, `test_link_input_hash_mismatch_blocks_automatic_link_confirmation`.
- **Результат:** валидная машинная связь может пройти без ручной отметки; подмена значения любого конца блокирует подтверждение.

### Целостность расчёта Reconciliation

- **Причина:** предварительный результат мог не доказывать совпадение версии/хеша входа, операции, формулы и итогового значения.
- **Изменённые файлы:** `app/contracts.py`, `app/engine.py`, `docs/reconciliation-integration.md`, `contracts/reconciliation-result-1.0.0.schema.json`.
- **Исправление:** Verification проверяет ссылочную и расчётную целостность перед окончательным статусом, не выполняя финансовый пересчёт. Точные требования к следующей версии Reconciliation описаны в handoff-документе.
- **Проверки:** `test_reconciliation_input_hash_mismatch_blocks_final_status`, `test_missing_reconciliation_input_hash_is_not_treated_as_verified`, `test_incompatible_reconciliation_extraction_version_blocks_final_status`, `test_operation_output_must_match_reconciliation_expected_value`, `test_operation_formula_must_reference_the_declared_inputs`, `test_missing_calculation_operations_remains_unproven`.
- **Результат:** тесты подтверждают, что неполное доказательство не превращается в установленный `matched` или `mismatch`.

### Контракты и upstream-интеграция

- **Причина:** upstream-примеры и схемы могут иметь разные фактические версии; новый результат требует сохранить совместимый формат для потребителей.
- **Изменённые файлы:** `app/contracts.py`, `app/models.py`, `contracts/upstream-sources.json`, `contracts/upstream/*.schema.json`, `contracts/verification-result-1.1.0.schema.json`, `docs/contracts.md`, `docs/reconciliation-integration.md`.
- **Исправление:** Extraction 1.2.0 и Linking 1.2.0 зафиксированы с commit SHA и schema hashes; выход обновлён версионированно до 1.1.0, legacy-адаптер для 1.0.0 сохранён. Несовпадение upstream Linking sample `contract_version=1.0.0` со схемой 1.2.0 явно диагностируется.
- **Проверки:** `test_synthetic_linking_12_contract_and_real_extraction_12_fixtures_validate`, `test_upstream_source_commits_and_schema_hashes_are_pinned`, `test_upstream_linking_example_is_detected_as_incompatible_with_declared_12_schema`, `test_output_schema_file_matches_pydantic_contract`.
- **Результат:** проверенные upstream refs совпали с pinned SHA; fixtures и JSON Schema проходят контрактные проверки.

### API, безопасность и хранение

- **Причина:** чтение результатов не было ограничено проектом, запросы не имели межсервисной аутентификации и границ размера/времени; необязательный provider мог удерживать транзакцию SQLite, а параллельные повторы могли дублировать запись.
- **Изменённые файлы:** `app/api.py`, `app/storage.py`, `docker-compose.yml`, `.env.example`, `tests/test_api.py`, `tests/test_verification_scenarios.py`.
- **Исправление:** добавлены токены по проектам, изоляция чтения, лимиты, безопасные ответы ошибок и loopback-конфигурация Compose. Provider вызывается вне транзакции; уникальный fingerprint разрешает конкурентные повторы идемпотентно.
- **Проверки:** `test_project_credentials_isolate_results_and_history`, `test_request_size_limit_and_validation_errors_do_not_echo_financial_values`, `test_parallel_identical_requests_store_one_idempotent_run`, `test_optional_llm_call_runs_outside_sqlite_transaction`.
- **Результат:** API/security, конкуренция и изоляция транзакций проходят тесты; `.env` исключён Git, пример ключа пустой.

### GitHub Actions CI и Docker Compose

- **Причина:** проверки не запускались автоматически на push и pull request.
- **Изменённые файлы:** `.github/workflows/ci.yml`, `README.md`, `docs/test-results.md`.
- **Исправление:** workflow запускает pytest на Python 3.11 и 3.12, проверяет Compose, собирает контейнер и выполняет синтетический HTTP smoke без Polza.
- **Проверки:** локальный эквивалент `python -m pytest --tb=short`, `docker compose config --quiet` и Compose smoke.
- **Результат:** локально `60 passed, 1 warning`; Docker Compose smoke вернул `matched`, полную проверку, доступные scoped GET и историю. GitHub Actions run [43503524091](https://github.com/artemnoor/phystech-trace-verification-engine/actions/runs/43503524091) прошёл на Python 3.11, Python 3.12 и в Docker Compose smoke.

## Что не заявляется

Полный E2E Parser → Reconciliation → Verification → Reporting не подтверждён: Reconciliation 1.0.0 остаётся предварительным, а Reporting Engine не подключён. Исторический live-тест Polza с синтетическими псевдонимными данными описан отдельно в [`test-results.md`](test-results.md); unit/mock проверки не выдаются за live-запуск.
