# Отчёт интеграции и сквозной проверки

## Источники кода

| Модуль | Исходный commit |
| --- | --- |
| Document Parser | `e6bb15e1fd4581d810d3426ea6558c9bb61231f6` |
| Structured Extraction | `1e922e284805f2c1b343b4cb369813c8073b67dd` |
| Document Linking | `28a3662cc0597093ad6264f70f591db19c37e061` |

Extraction и Linking импортированы git subtree, без вложенных репозиториев; история исходников сохранена. Работа ведётся в ветке `feat/phystech-trace-integration`.

## Проверки

| Команда / проверка | Результат |
| --- | --- |
| `python -m unittest discover -s backend/tests` | 153 теста пройдены, включая Parser/OCR и выдачу байт исходного XLSX без изменения |
| `npm test` в `services/structured-extraction` | 40/40 пройдены; rules-only контрольный комплект распознал 46/46 строк, 521/521 provenance-меток и 13/13 полей |
| `npm test` в `services/document-linking` | 46 пройдены, 0 упали, 5 пропущены: инфраструктурные интеграции без доступных тестовых DB/Redis и live-Polza сценарии без ключа |
| `npm run build` в `services/document-linking` | TypeScript, Vite и server bundles собраны успешно |
| `npm run typecheck` и `npm run build` во `frontend` | Успешно |
| `python -m unittest discover -s tests/contracts -v` | 7 контрактных тестов пройдены: JSON Schema, pinned upstream-контракты и реальные fixtures |
| `python -m py_compile gateway/main.py tests/contracts/test_contracts.py tests/e2e/run_e2e.py` | Успешно |
| `docker compose config --quiet` | Успешно |
| `docker compose up --build -d` | Образы собраны; Postgres, Redis, Parser, Extraction, Linking API, Linking worker, Gateway и Vue frontend перешли в `healthy` |
| Проверка Vue через Playwright | UI открыт в Chromium; XLSX evidence показывает лист `Реестр`, ячейку `E2`, исходное значение `35000` и переход к исходному файлу |

Standalone Extraction image в Compose собран из реального upstream-кода и работает без Workers/D1. Legacy `test:api` upstream-пакета проверяет Cloudflare Worker на `127.0.0.1:5173`, поэтому он не является smoke-тестом новой standalone API; вместо него HTTP API Extraction проверен общим E2E. Сборка и запуск импортированных Cloudflare UI/Worker артефактов не заявляются как отдельная проверка.

## Сквозной HTTP E2E

Запущен `python tests/e2e/run_e2e.py --base-url http://localhost:8084` на синтетическом комплекте. Проверка прошла через публичные HTTP API Compose-сервисов и дала **частичный результат**:

- Загружены PDF, XLSX, DOCX и PNG. Реальные Parser и Extraction вернули результаты для всех четырёх файлов.
- PDF сохранил Parser provenance и page/bbox locator; XLSX сохранил адрес `Реестр!E2`; исходные байты всех загруженных файлов разрешаются без потери.
- DOCX классифицирован как акт. Повтор PNG обнаружен как дубликат.
- Невалидный Parser payload получил диагностируемую контрактную ошибку.
- Linking вызван через сервисный API и корректно вернул `503`: `POLZA_API_KEY` не настроен. Повтор этапа проверил, что результаты Parser/Extraction и их IDs остались сохранены.
- Проверены `/health`, `/openapi.json`, `/docs` трёх модулей, Gateway и отдача production Vue UI.

Отчёт конкретного синтетического запуска: [`tests/e2e/results/latest-run.json`](../tests/e2e/results/latest-run.json). Project ID: `f4ecde31-6d02-42f8-b475-27c727f289ca`; четыре документа и их extraction IDs сохранены в PostgreSQL Compose volume. Exit code `2` для этого запуска предусмотрен runner-ом и обозначает проверенный сценарий «Parser/Extraction успешны, Linking недоступен».

## Непроверенные сценарии и ограничения

В окружении отсутствовал `POLZA_API_KEY`, поэтому настоящий вызов внешней модели, LLM-связи, подтверждение evidence на результате Linking и полный E2E до конечных связей не выполнялись. В тестах Linking есть сценарии с подменённым клиентом модели; они не выдаются за live LLM E2E. Данные E2E синтетические, согласие на внешнюю обработку включено явно, однако без ключа ничего не отправлялось.

Для полного прогона задайте разрешённый `POLZA_API_KEY` в `.env`, загрузите только открытый, синтетический или обезличенный комплект и включите явное согласие для проекта. Затем повторите команду из [`tests/e2e/README.md`](../tests/e2e/README.md). Текущий результат остаётся диагностируемым и сохранённым; сервисы Compose оставлены запущенными.
