# Отчёт об устранении дефектов

Дата проверки: 13 ноября 2026 года. Работа выполнена в существующей архитектуре FastAPI, Decimal Engine, LLM Planner и Reconciliation contract 1.0.0.

## Исправления

| Проблема и причина | Изменение | Проверка |
| --- | --- | --- |
| Целевой показатель КФЗ мог оказаться в списке источников, включая косвенное включение из того же отчёта. | `engine.py` запрещает любой `kfz_report` в арифметическом плане; `service.py` сохраняет target только как контекст и происхождение. | `test_kfz_target_cannot_be_used_as_its_own_evidence`; synthetic acceptance проверяет, что target-документ отсутствует среди использованных источников. |
| Проверялись отдельные шаги, но скрытые шаги, повторный учёт через DAG-узлы, циклы, ссылки и кратность могли разойтись с итоговым выражением. | `engine.py` раскрывает зависимости от `result_step_id`, считает факты в итоговом выражении и проверяет достижимость, арность, ID и ссылки. | Тесты на недостижимые шаги, повторный учёт через subtotal, отсутствие аргумента вычитания и деление на ноль. |
| Псевдонимы Linking-групп могли превратиться в `source_unknown`; исходные ID и финансовые значения не должны уходить в Planner. | `planner.py` согласует псевдонимы документов, строк, фактов и связей; исключает raw ID, locator, source value и числа; связывает алиасы назад перед проверкой плана. | `test_planner_payload_contains_pseudonymized_link_graph_without_raw_locators_or_source_values`. |
| Ранее подтверждённое решение могло пережить изменение Extraction или Linking. | `service.py` хеширует snapshot, версии Extraction, Linking, выбранные и принятые факты/связи и само решение. Неприкреплённые либо изменившиеся решения блокируются. | Тесты изменения подтверждённой суммы и нового Linking snapshot. |
| `LLM_TRUSTED_LOCAL=true` могло ошибочно восприниматься как разрешение отправки закрытых данных на любой URL. | Добавлен `security.py`: закрытые данные допускаются только для loopback/private IP, localhost либо точного хоста из `LLM_TRUSTED_HOSTS`. Внешний вызов требует open/anonymized и явного `external_llm_allowed`. Planner использует псевдонимы и не передаёт денежные значения. | `test_trusted_local_flag_never_sends_confidential_data_to_an_external_api` проверяет, что HTTP-вызовов нет; проверяются alias payload и значения-кандидаты. |
| Ошибка отдельного плана или вычисления могла стать HTTP 500 либо скрыть успешные другие показатели. | `service.py` переводит сбои плана/деления на ноль в diagnostics с путём, изолирует цели и очищает `expected_value`/точное значение при неуспехе. Контрактные ошибки остаются отдельными `422`. | Тест деления на ноль, per-target isolation, API contract errors; полный API и schema round trip. |
| Наличие какой-либо связи могло приниматься за доказательство применимости; акт, счёт, реестр и итоги строк могли дублировать одну операцию. | `engine.py` связывает факты только с относящимися к ним строками, транзитивно запрещает суммирование сопоставленных строк и summary с line items. Междокументальная независимость требует отдельного human-confirmed признака. Для LLM-плана дополнительно нужна подтверждённая row-aware связь с target. | Тесты пары и цепочки «акт—счёт—реестр», отсутствие независимости без подтверждения и LLM без проверенного пути. |
| Проверка периода была только документной, смешивались типы сумм/валюты/единицы, а required document type проверялся по полному комплекту. | `facts.py` предпочитает operation/service date/period; `engine.py` блокирует частичное пересечение, неизвестные периоды, разные экономические типы, валюты, размерности и необоснованные gross/net преобразования. `service.py` считает обязательные типы по отобранным источникам. | Регрессии периода операции и частичного пересечения, actual/planned, валюты/единицы, НДС и требуемого типа документа. |
| Входной Linking мог не соответствовать входным Extraction по версии, ID и hash. | `contracts.py` сверяет состав и версии, проверяет формат hash и согласованность при наличии исходного hash. API не адаптирует Linking 1.0.0 молча к 1.2.0. | Все шесть upstream Extraction fixtures валидируются по 1.2.0 schema; legacy Linking fixture возвращает точную диагностику версии. |
| API не имел проектной авторизации, а одинаковый результат мог читаться из общего хранилища. | `api.py`, `config.py`, `storage.py`: bearer token и `X-Project-ID`, проверка production-конфигурации, project-scoped storage по хешу проекта, POST idempotency (201/200). | API тесты авторизации, scope, повторного POST и OpenAPI; CI проверяет Docker HTTP endpoints. |
| Нет успешного upstream расчёта, который можно было бы подтвердить имеющимися fixtures. | Существующий пример остаётся честным `manual_review`: цель относится к Q1, источник — к апрелю, а опубликованный Linking fixture — устаревший 1.0.0. Добавлен отдельный полностью помеченный synthetic комплект и независимый golden reference. | Synthetic acceptance повторно рассчитывает `550.00 RUB`, сверяет provenance пяти сумм с исходными Extraction и валидирует output schema. |
| Не было непрерывной проверки container/API. | `.github/workflows/ci.yml` выполняет pytest, перестраивает synthetic acceptance, собирает контейнер и проверяет health/docs/OpenAPI. | Локально выполнены Docker build и smoke через `/health`, `/openapi.json`, `/docs`. |

## Изменённые файлы

- Расчёт и API: `reconciliation_engine/engine.py`, `facts.py`, `service.py`, `planner.py`, `plans.py`, `models.py`, `api.py`, `contracts.py`, `config.py`, `security.py`, `storage.py`.
- Контракты и настройки: `schemas/reconciliation-request-1.0.0.schema.json`, `schemas/reconciliation-result-1.0.0.schema.json`, `.env.example`, `prompts/calculation-plan.v1.0.0.txt`.
- Тестирование: `tests/conftest.py`, `test_api.py`, `test_calculation_engine.py`, `test_planner_payload.py`, `test_remediation.py`, `test_synthetic_acceptance.py`.
- Приёмочные данные: `examples/build_synthetic_acceptance.py`, `examples/synthetic/acceptance-request.json`, `acceptance-plan.json`, `acceptance-result.json`, `golden-reference.json`.
- Документация и CI: `README.md`, `docs/architecture.md`, `docs/calculation-model.md`, `docs/contracts.md`, `docs/test-results.md`, `.github/workflows/ci.yml`.

## Фактические результаты проверки

- Последний полный прогон: `pytest --durations=10` — **64 passed in 67.82s**, включая трассировку provenance synthetic источников.
- Целевые API/schema, synthetic acceptance и точный путь деления на ноль: **4 passed**; отдельный повтор synthetic acceptance после пересборки: **2 passed**.
- `python examples/build_synthetic_acceptance.py`: успешный расчёт, `status=calculated`, `expected_value=550.00 RUB`.
- Docker: `docker build -t reconciliation-engine:smoke .` — успешно. Запущенный контейнер вернул `/health = ok`, `/docs = 200`; OpenAPI включил `/api/v1/reconciliations`.
- Реальный LLM Planner через OpenAI-compatible endpoint не запускался: в текущем окружении нет настроенного API key и разрешённого test endpoint. HTTP mock-тесты обозначены только как guard/regression checks, не как реальный модельный прогон.

## Оставшиеся ограничения

- Нет реального upstream-положительного расчёта: предоставленные fixtures не дают совпадающей области периода и подтверждённого Linking 1.2.0 evidence graph. Сумму не фабриковали; реальный пример остаётся `manual_review`, синтетический сценарий не выдаётся за upstream.
- Реальный LLM API и CI-run на GitHub появятся только после отправки изменений; локальный Docker smoke не проверяет поставщика модели.
- Общая Gateway-интеграция намеренно не выполнялась.
- Междокументальное суммирование и LLM-применимость зависят от проверенных человеческих подтверждений; автоматическое отсутствие связи не считается доказательством независимости.
