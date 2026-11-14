[← README](../README.md) · [Для жюри →](jury-guide.md)

# Запуск и демонстрация

## Окружение

Docker Engine / Docker Desktop с Linux containers, Compose v2.24+, Git и доступ в интернет для загрузки образов, зависимостей и OCR-моделей. Для самостоятельного запуска тестов: Python 3.11+, Node.js 22.13+. Docker-сценарий не требует установки Python/Node на хост.

Для рабочего стенда удобно выделить 4 CPU и 16 GB RAM. Сборка Parser устанавливает CPU-версию PyTorch и Docling; повторные сборки используют Docker cache. Постоянные данные и модели хранятся в именованных томах.

## Установка

```sh
git clone https://github.com/artemnoor/list-document-viewer.git
cd list-document-viewer/phystech-trace
cp .env.example .env
```

PowerShell: `Copy-Item .env.example .env`. Заполните `POLZA_API_KEY` собственным ключом Polza AI. Ключ остаётся на сервере и не включается в клиентскую сборку. Для внешних модельных этапов выбирайте открытые/обезличенные/синтетические данные и разрешение обработки в проекте.

```sh
docker compose up -d --build
docker compose ps
```

Интерфейс: [localhost:8080](http://localhost:8080). Регистрация → проект → КФЗ и первичка → проверка → результаты. В настройках укажите нужную строку/этап и период. Максимальный размер файла — 25 MiB.

## Настройки

| Переменная | Назначение |
|---|---|
| `POLZA_API_KEY` | Ваш ключ внешнего модельного провайдера |
| `POSTGRES_PASSWORD` | Пароль PostgreSQL; задайте собственный для стенда |
| `API_BEARER_TOKEN` | Внутренний токен Linking; задайте собственный |
| `LLM_ENABLED` | Включение модельного связывания |
| `RECONCILIATION_LLM_ENABLED` | Модельное планирование расчёта |
| `LLM_MAX_CALLS_PER_RUN` | Лимит вызовов семантического запуска |
| `LLM_MAX_RUN_MS` | Лимит длительности семантического запуска |
| `LLM_TIMEOUT_MS` | Тайм-аут одного модельного запроса |

Полный пример: [`.env.example`](../phystech-trace/.env.example). Docker Hub/реестры пакетов используются при сборке, источники OCR-весов — при первой загрузке моделей, Polza AI — при разрешённых модельных вызовах.

## Два типовых сценария

**1. Совпадение.** КФЗ содержит общехозяйственные затраты 120 000 ₽ за январь 2026. Два независимых акта того же договора и периода: 70 000 и 50 000 ₽. Ожидается `matched`, ожидание 120 000 ₽, разница 0, две ссылки на первичку. Это сценарий `01-independent-sum` в [публичном корпусе](../benchmarks/cases.json).

**2. Расхождение и неполные данные.** КФЗ содержит 132 500 ₽, первичка подтверждает 120 000 ₽. Ожидается `mismatch`, разница 12 500 ₽. Документ другого договора/периода исключается с причиной, копия не увеличивает сумму. Если у отдельного показателя нет достаточной первички, он остаётся `insufficient_data`, без выдуманного нулевого ожидания. Сценарии `02`, `03`, `04`, `05`, `06`, `15` в том же корпусе.

## Сервисы и остановка

| Компонент | Локальный адрес |
|---|---|
| Интерфейс | `http://localhost:8080` |
| Parser Swagger | `http://localhost:8081/docs` |
| Extraction Swagger | `http://localhost:8082/docs` |
| Linking Swagger | `http://localhost:8083/docs` |
| Gateway Swagger | `http://localhost:8084/docs` |
| Reconciliation Swagger | `http://localhost:8085/docs` |
| Verification Swagger | `http://localhost:8086/docs` |

```sh
docker compose logs --tail=100 gateway
docker compose down
```

`down` сохраняет тома. `docker compose down -v` удаляет данные этого Compose-проекта: применяйте только для намеренного сброса стенда. Проверяющий скрипт [verify_docker.py](../scripts/verify_docker.py) создаёт собственный случайный Compose-проект, не публикует порты и после проверки очищает только его.

## См. также

[Для жюри](jury-guide.md) · [Бенчмарки](../benchmarks/README.md) · [Архитектура](../phystech-trace/docs/architecture.md)
