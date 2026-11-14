# Отчёт об устранении проблем

**Проект:** Phystech Trace — Verification Engine 1.2.0

**Дата проверок:** 14 ноября 2026

**Область:** локальный Verification Engine, совместимость с Extraction/Linking 1.2.0 и обеими известными формами Reconciliation 1.0.0.

## 1. Большие комплекты и передача артефактов

- **Причина:** лимит 2 МиБ отвергал большой набор JSON fixtures до contract validation; передача полной коллекции на каждый запуск увеличивала повторное чтение данных.
- **Изменённые файлы:** `app/api.py`, `app/artifact_adapter.py`, `app/models.py`, `.env.example`, `docker-compose.yml`, `tests/test_api.py`, `docs/contracts.md`.
- **Исправление:** лимит по умолчанию увеличен до 16 МиБ и ограничен жёстким максимумом 64 МиБ; добавлен `POST /api/v1/verifications/from-artifacts` с project-scoped content-addressed JSON, проверкой SHA-256/размера/пути и ограниченным кешем. Загрузки произвольных файлов через API нет.
- **Проверяющий тест:** `test_full_upstream_bundle_over_two_mib_is_not_rejected_by_default_limit`, `test_all_published_upstream_fixture_files_reach_contract_validation_over_two_mib`, `test_artifact_reference_endpoint_is_project_scoped_and_idempotent`.
- **Фактический результат:** 2,428,762-байтовый extraction bundle обработан с HTTP 200; полный набор, включающий legacy Linking sample, дошёл до проверки контракта и получил HTTP 422 из-за несовместимой версии вместо 413. Artifact-reference route обработал ссылки, подтвердил повторную идемпотентность и отклонил tampered content/чужой scope.

## 2. Агрегированные статусы и полнота

- **Причина:** предыдущий порядок мог скрыть доказанное расхождение среди unresolved значений, а общий статус не выражал отдельно полноту охвата.
- **Изменённые файлы:** `app/classification.py`, `app/engine.py`, `app/models.py`, `contracts/verification-result-1.2.0.schema.json`, `tests/test_verification_scenarios.py`, `docs/verification-logic.md`, `examples/response-*.json`.
- **Исправление:** `mismatch` имеет приоритет при агрегации; непроверенные статусы затем блокируют `matched`. Контракт 1.2.0 добавляет `conclusion.has_proven_mismatch`, `coverage_complete` и отдельные счётчики mismatch/unresolved/not-applicable.
- **Проверяющий тест:** `test_proven_mismatch_takes_precedence_over_unresolved_and_not_applicable`, `test_matched_is_not_conclusive_when_unresolved_indicator_is_present`, `test_proven_mismatch_is_reported_with_partial_unresolved_and_not_applicable_coverage`, `test_aggregate_status_exposes_not_applicable_coverage_instead_of_matched`.
- **Фактический результат:** regression checks проходят; смешанный пример отдаёт общий `mismatch` с `coverage_complete=false` и раздельными количествами непроверенных и неприменимых значений.

## 3. Проверяемость расчётов Reconciliation

- **Причина:** совпадающие заявленные `output_value` и `expected_value` можно было выдать без доказательства, что операция действительно использовала исходные значения.
- **Изменённые файлы:** `app/reconciliation_adapter.py`, `app/reconciliation_proof.py`, `app/engine.py`, `app/contracts.py`, `contracts/reconciliation-engine/`, `contracts/reconciliation-engine-sources.json`, `tests/fixtures/{synthetic,upstream}/reconciliation-engine/`, `tests/test_verification_scenarios.py`, `docs/reconciliation-integration.md`.
- **Исправление:** добавлен отдельный адаптер нативной формы `input_snapshot`/`calculations` с сохранением IDs и ссылок. Verification повторно проверяет Extraction snapshot hashes, fact IDs и hashes по исходному wrapper, provenance, полноту included/excluded фактов, связность шага/trace и formula. Нативные `sum/add/subtract/multiply/divide/round` и поддерживаемые provisional operations независимо вычисляются через Decimal. Неподдерживаемая или противоречивая математика не получает окончательный matched/mismatch.
- **Проверяющий тест:** `test_native_reconciliation_decimal_proof_and_fact_hashes_are_recomputed`, `test_matching_declared_output_and_expected_value_cannot_hide_wrong_arithmetic`, `test_operation_formula_must_encode_the_declared_operation_type`, `test_operation_output_must_match_reconciliation_expected_value`, `test_available_real_reconciliation_result_is_consumed_without_false_match`.
- **Фактический результат:** synthetic acceptance fixture подтверждает Decimal сумму и source hashes; изменённый trace/result отвергается. Доступный реальный upstream result проверяется, но остаётся `insufficient_data`: upstream объявил `manual_review`, не предоставил used sources/trace, а объявленный Linking run отсутствует во входе.

## 4. Исторические результаты

- **Причина:** автоматическое преобразование старого `matched`/`mismatch` в новый контракт могло выглядеть как повторно проверенный вывод.
- **Изменённые файлы:** `app/storage.py`, `app/models.py`, `tests/test_api.py`, `docs/contracts.md`.
- **Исправление:** SQLite adapter поддерживает результаты 1.0.0 и 1.1.0, сохраняет старые значения в `legacy_status`/`legacy_overall_status`, ставит `integrity_status=legacy_unverified`, сбрасывает completeness и понижает исторические matched/mismatch до `needs_review`. История отражает мигрированный статус.
- **Проверяющий тест:** `test_api_preserves_idempotent_legacy_records_without_input_metadata`.
- **Фактический результат:** повторный запрос и GET возвращают версию 1.2.0 с явной legacy отметкой; полнота false, доказанный mismatch не приписывается.

## 5. Upstream и Reporting contracts

- **Причина:** прежняя документация считала provisional Reconciliation единственной формой и устарела после появления опубликованного native engine result; выход нуждался в явной новой версии.
- **Изменённые файлы:** `app/contracts.py`, `app/reconciliation_adapter.py`, `app/reconciliation_proof.py`, `app/models.py`, `contracts/verification-result-1.2.0.schema.json`, `contracts/reconciliation-engine-sources.json`, `docs/contracts.md`, `docs/reconciliation-integration.md`, `README.md`.
- **Исправление:** Extraction 1.2.0 и Linking 1.2.0 сохранены. Отдельные адаптеры различают provisional и published Reconciliation 1.0.0 по форме, не смешивая одинаковый номер контракта. Verification JSON аддитивно поднят до 1.2.0; схемы 1.0.0/1.1.0 сохранены.
- **Проверяющий тест:** `test_synthetic_linking_12_contract_and_real_extraction_12_fixtures_validate`, `test_upstream_linking_example_is_detected_as_incompatible_with_declared_12_schema`, `test_output_schema_file_matches_pydantic_contract`.
- **Фактический результат:** upstream Extraction fixtures и синтетический Linking 1.2.0 валидируются; старый Linking sample ожидаемо отклоняется; schemas и примеры ответа 1.2.0 проходят JSON Schema validation.

## 6. Повторяемость и API

- **Причина:** для интеграции необходимы project scope, ограничение размера/времени, безопасные ошибки и отсутствие параллельных duplicate runs.
- **Изменённые файлы:** `app/api.py`, `app/storage.py`, `tests/test_api.py`, `.env.example`, `docker-compose.yml`, `.github/workflows/ci.yml`.
- **Исправление:** сервис сохраняет token-per-project auth, project-scoped reads, ограниченное request body/time, generic ошибки без эха financial data, уникальность fingerprint и короткую SQLite транзакцию после детерминированной/optional provider обработки. CI проверяет Python 3.11/3.12 и Compose; smoke работает с Polza disabled.
- **Проверяющий тест:** `test_project_credentials_isolate_results_and_history`, `test_request_size_limit_and_validation_errors_do_not_echo_financial_values`, `test_parallel_identical_requests_store_one_idempotent_run`, `test_optional_llm_call_runs_outside_sqlite_transaction`.
- **Фактический результат:** полный набор `python -m pytest --tb=short` завершился **72 passed**; Compose configuration, build, health/docs/OpenAPI, новый synthetic POST, scoped GET и history прошли. Ни один live Polza запрос в этом прогоне не выполнялся.

## Ограничение интеграции

Есть реальный upstream Reconciliation Engine result, но он намеренно неполный и не доказывает успешный расчёт. Synthetic engine acceptance проверяет арифметику адаптера отдельно и не подменяет production integration result. Полный Phystech Trace E2E до Reporting не заявляется. GitHub Actions run после push commit a4209a6 завершился успешно на Python 3.11, Python 3.12 и Docker Compose smoke; [результаты workflow](https://github.com/artemnoor/phystech-trace-verification-engine/actions/runs/43513739458) сохранены в [test-results.md](test-results.md).
