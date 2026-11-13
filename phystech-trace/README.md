# Phystech Trace

Модульная обработка комплектов КФЗ: существующий Python Document Parser → Structured Extraction 1.2.0 → Document Linking 1.2.0. Сервисы запускаются отдельно; Gateway сохраняет проекты, этапы и промежуточные результаты. Основной интерфейс — Vue 3 + TypeScript.

## Запуск

Из этого каталога выполните:

```powershell
docker compose up --build
```

Откройте http://localhost:8080. Первый build Parser image займёт больше времени из-за Docling и OCR-зависимостей. При первом OCR Parser может загрузить модели в постоянный volume.

Остановка: `docker compose down`. Compose volumes сохраняют PostgreSQL, Redis, загруженные оригиналы и OCR-модели. Для удаления данных вместе с контейнерами: `docker compose down -v`.

## Swagger и health

| Сервис | Swagger UI | Health | OpenAPI |
| --- | --- | --- | --- |
| Document Parser | http://localhost:8081/docs | http://localhost:8081/health | http://localhost:8081/openapi.json |
| Structured Extraction | http://localhost:8082/docs | http://localhost:8082/health | http://localhost:8082/openapi.json |
| Document Linking | http://localhost:8083/docs | http://localhost:8083/health | http://localhost:8083/openapi.json |
| Gateway | http://localhost:8084/docs | http://localhost:8084/health | http://localhost:8084/openapi.json |

В Compose Linking API требует локальный bearer token. Gateway добавляет его сам; Vue UI обращается только через Gateway. PostgreSQL, Redis и Linking worker не опубликованы на хост.

## Конфигурация и приватность

Compose запускается без `.env`. Чтобы задать свои секреты, скопируйте `.env.example` в `.env`. `POLZA_API_KEY` необязателен: без него локальный Parser и rules-only Extraction доступны, а Linking сообщает диагностируемую ошибку отсутствующего ключа.

Внешняя модель не вызывается для конфиденциальных документов. Для проекта с открытыми, синтетическими или обезличенными данными требуется явно включить согласие при создании проекта. Gateway и Linking API проверяют это разрешение. Parser контейнер не получает Polza key; parser-side AI review в Compose отключён.

Форматы и лимиты соответствуют существующему Parser: PDF, изображения, DOCX, XLSX/XLSM, CSV, TXT и другие заявленные форматы; ограничение загрузки — 25 MiB.

## Проверки

```powershell
python -m unittest discover -s tests/contracts -v
python tests/e2e/run_e2e.py --base-url http://localhost:8084
```

E2E использует HTTP API настоящих сервисов и синтетические fixtures. Результат проверки Linking и реального вызова внешней модели фиксируется отдельно. Mock LLM тесты не являются проверкой Polza.

В текущем окружении Parser и Extraction прошли E2E на PDF/XLSX/DOCX/PNG, но полный Linking этап не завершился: `POLZA_API_KEY` не задан. Точный статус и сохранённые IDs см. в [`docs/integration-report.md`](docs/integration-report.md) и [`tests/e2e/results/latest-run.json`](tests/e2e/results/latest-run.json).

См. [`docs/architecture.md`](docs/architecture.md), [`docs/data-flow.md`](docs/data-flow.md), [`docs/contracts.md`](docs/contracts.md) и [`docs/integration-report.md`](docs/integration-report.md).
