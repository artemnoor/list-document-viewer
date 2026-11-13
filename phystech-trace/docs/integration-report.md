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
| `npm test` в `services/document-linking` без live ключа | 46 пройдены, 0 упали, 5 пропущены: инфраструктурные интеграции и live-Polza сценарии |
| `npm test` в `services/document-linking` с Windows `POLZA_AI_API_KEY` | 47 пройдены, 1 упал, 3 пропущены из 51; неоднозначный live demo прошёл через Polza (2 вызова, 0 ожидаемых связей), отдельный live addendum-тест истёк по таймауту 120 секунд |
| `npm run build` в `services/document-linking` | TypeScript, Vite и server bundles собраны успешно |
| `npm run typecheck` и `npm run build` во `frontend` | Успешно |
| `python -m unittest discover -s tests/contracts -v` | 7 контрактных тестов пройдены: JSON Schema, pinned upstream-контракты и реальные fixtures |
| `python -m py_compile gateway/main.py tests/contracts/test_contracts.py tests/e2e/run_e2e.py tests/e2e/retry_linking.py tests/e2e/review_decisions.py tests/e2e/verify_saved_project.py` | Успешно |
| `docker compose config --quiet` | Успешно; Compose принимает `POLZA_API_KEY` или `POLZA_AI_API_KEY`, LLM timeout 120 секунд и максимум 230 000 входных токенов (пределы Linking) |
| `docker compose up --build -d` | Образы собраны; Postgres, Redis, Parser, Extraction, Linking API, Linking worker, Gateway и Vue frontend перешли в `healthy`; после live-тестов Extraction восстановлен с настроенным ключом |
| Проверка Vue через Playwright | UI открыт в Chromium; XLSX evidence показывает лист `Реестр`, ячейку `E2`, исходное значение `35000` и переход к исходному файлу |

Standalone Extraction image в Compose собран из реального upstream-кода и работает без Workers/D1. Legacy `test:api` upstream-пакета проверяет Cloudflare Worker на `127.0.0.1:5173`, поэтому он не является smoke-тестом новой standalone API; вместо него HTTP API Extraction проверен общим E2E. Сборка и запуск импортированных Cloudflare UI/Worker артефактов не заявляются как отдельная проверка.

## Сквозной HTTP E2E

### Широкий комплект файлов

Через Gateway были загружены пять уникальных синтетических документов: КФЗ PDF, сложный PDF fixture со сканированными страницами, XLSX, DOCX и PNG; повторная загрузка PNG проверила дедупликацию. Parser и rules-only Extraction завершили обработку комплекта. Проверены PDF page/bbox, XLSX ячейки, сохранность document/extraction IDs, исходных байт, переход к исходной PDF странице, контрактная ошибка на невалидный Parser payload и Swagger всех модулей.

Настроенная Extraction LLM на первом варианте набора вернула `POLZA_UNGROUNDED_OUTPUT`; такой результат был отклонён сервисом. Повтор широкого набора был выполнен в rules-only режиме, не подменяя Parser, Extraction или Linking алгоритмы.

Для полного набора Linking действительно вызывал Polza. При исходном лимите 180 000 оценка финального объединения превышала бюджет контекста после 9/9 обработанных фрагментов. После настройки максимально допустимых сервисом 230 000 входных токенов и 120 секунд на вызов другой полный прогон на 5-документном входе завершился ошибкой `Gemma вернула невалидный JSON` после 7 вызовов и 2/8 фрагментов. Повтор Parser/Extraction не запускался; прежние результаты и IDs сохранены. Снимок неуспешного live прогона: [`tests/e2e/results/full-set-live-attempt.json`](../tests/e2e/results/full-set-live-attempt.json).

### Компактный полный live-процесс

Команда `python tests/e2e/run_e2e.py --compact-linking --base-url http://localhost:8084 --timeout 1800` прошла через все настоящие HTTP API на синтетических PDF/XLSX/DOCX с одной известной общей строкой. Extraction работал в rules-only режиме; Document Linking вызвал реальную Polza-модель `google/gemma-4-26b-a4b-it` 3 раза. Состояние проекта `ab5f2d87-1759-450d-a3dd-38c33b9ec91f` — `completed`.

Получены три ожидаемые связи: `report_summarizes_registry`, `act_validates_registry`, `act_contains_line_item`. Все 16 сторон evidence разрешились до точных извлечённых значений и provenance; совпали описание, количество и сумма строки работ, contract reference и итоговая сумма. Сохранённые источники и PDF page endpoint доступны после завершения обработки. Результат: [`tests/e2e/results/latest-run.json`](../tests/e2e/results/latest-run.json).

На тех же live-данных `python tests/e2e/review_decisions.py --project-id ab5f2d87-1759-450d-a3dd-38c33b9ec91f` подтвердила связь `report_summarizes_registry`, отклонила `act_validates_registry`, проверила неизменность evidence и устойчивость решений при повторном чтении. Отчёт: [`tests/e2e/results/review-decisions.json`](../tests/e2e/results/review-decisions.json).

## Ограничения

- Широкий пятидокументный набор прошёл Parser и Extraction, но live Linking всего набора ограничен контекстом/невалидным ответом модели. Успешный реальный Linker E2E выполнен на компактном синтетическом наборе из трёх документов.
- LLM-assisted Extraction на тестовом синтетическом наборе вернул `POLZA_UNGROUNDED_OUTPUT`; проверенные Parser и Extraction результаты для E2E получены в существующем rules-only режиме. Самостоятельные mock/unit тесты Extraction не считаются live-модельным E2E.
- `npm test` Document Linking с live ключом не полностью прошёл: один upstream live сценарий истёк по таймауту. Его ошибка сохранена в выводе запуска; успешный трёхдокументный E2E и неоднозначный demo не заменяют этот тест.
- Внешней модели передавались только синтетические данные с явным согласием проекта. Ключ читался из Windows `POLZA_AI_API_KEY`; его значение не записывалось в репозиторий и не выводилось.

Compose оставлен запущенным, все сервисы `healthy`. Чтобы повторить проверки, используйте команды из [`README.md`](../README.md) и [`tests/e2e/README.md`](../tests/e2e/README.md).
