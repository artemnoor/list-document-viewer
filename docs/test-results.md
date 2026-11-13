# Исходный baseline до hardening

Проверено 13 ноября 2026 года.

- `pytest`: **46 passed** в последнем завершённом прогоне. Включает шесть настоящих upstream Extraction 1.2.0 fixtures, проверку legacy Linking 1.0.0 примера, API POST/GET round-trip, валидацию API-ответа опубликованной result schema, отдельные contract tests, псевдонимизацию LLM payload, независимые планы и Decimal арифметику. Предупреждений pytest нет. LLM mock не выдаётся за реальный модельный прогон.
- API тестами через ASGI: `/health`, `/docs`, `/openapi.json` работают; POST → GET сохраняет и возвращает ответ в формате result contract 1.0.0.
- Валидный пример результата специально показывает `manual_review` и `expected_value=null`: указанный целевой показатель относится к Q1, а акт-источник — к апрелю. Вычисленная сумма не публикуется как ожидаемая для несовпадающих периодов.
- Арифметическая воспроизводимость: числовые тесты отдельно фиксируют сумму пяти реальных строк акта `286500 + 93600 + 99600 + 158700 + 541900 = 1180300`.
- Сквозной LLM-прогон не выполнялся: в среде не настроены `LLM_API_KEY`, `OPENAI_API_KEY` или `POLZA_API_KEY`. Тест проверяет только блокировку закрытых данных и разрешение локального режима при явной настройке, не имитирует модель.

Тесты проверяют опубликованный JSON Schema напрямую и не зависят от Pydantic-модели реализации при contract validation. AI-планирование в реальном внешнем endpoint остаётся отдельной непроверенной интеграцией до появления разрешённой конфигурации. Docker smoke после изменения result contract не запускался.

## Текущий прогон после hardening

- Полный набор с тестами безопасности, snapshot binding, изоляции API, DAG и synthetic acceptance: **64 passed** (`pytest --durations=10`, 67.82 s). Включает разрешение provenance synthetic источников обратно в строки Extraction.
- `python examples/build_synthetic_acceptance.py`: **успешно**, синтетический результат `550.00 RUB`; в комплекте сохранены request, plan, result и golden reference.
- `docker build -t reconciliation-engine:smoke .`: **успешно**.
- Запущенный контейнер: `/health` → `ok`, `/docs` → HTTP 200, `/openapi.json` содержит reconciliation API route.
- Настроенного OpenAI-compatible API key или разрешённого endpoint нет; реальный LLM-прогон не выполнялся. Закрытые данные на внешний endpoint не отправлялись.
- Реальный upstream fixture остаётся `manual_review`: доступный акт относится к апрелю, целевой КФЗ — к Q1; единственный сохранённый Linking output имеет legacy версию 1.0.0. Синтетический acceptance не считается upstream-подтверждением.
