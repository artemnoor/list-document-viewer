# KFZ Document Linking

Document Linking принимает JSON-контракты Structured Extraction, передаёт комплект Gemma 4 26B A4B через Polza AI, технически проверяет доказательства и сохраняет результат. Инфраструктура: Node.js 22, Hono, PostgreSQL, Redis, BullMQ и React.

## Docker Compose: Windows 11 и VPS

Установите Docker Desktop с Compose v2 на Windows 11 либо Docker Engine и Compose v2 на VPS. Скопируйте шаблон и заполните секреты:

```powershell
Copy-Item .env.example .env
# Сгенерируйте два разных секрета длиной не менее 32 символов:
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
[Convert]::ToBase64String($bytes) -replace '[+/=]', ''
# Повторите генерацию и укажите значения в POSTGRES_PASSWORD и API_BEARER_TOKEN в .env
```

В `POSTGRES_PASSWORD` и `API_BEARER_TOKEN` нельзя оставлять пустые, короткие, одинаковые, тестовые или примерные значения. Production guard проверяет их до старта PostgreSQL, API и Worker. Ключ `POLZA_API_KEY` нужен для создания заданий анализа; без него приложение и интерфейс запускаются, а API явно откажет в анализе.

```powershell
docker compose up --build
```

Откройте http://localhost:3000. По умолчанию PostgreSQL доступен только на `127.0.0.1:55432`, Redis — только на `127.0.0.1:56379`; интерфейс/API — на порту `3000`. Поменять внешние порты можно через `PG_PORT`, `REDIS_PORT` и `PORT`. PostgreSQL и Redis используют постоянные volumes. Для сохранения данных останавливайте сервисы командой `docker compose down`, не добавляя `-v`.

Для VPS задайте секреты в `.env`, настройте внешний TLS reverse proxy и откройте наружу только HTTP(S) порт приложения. PostgreSQL и Redis в Compose привязаны к loopback хоста.

## Локальная разработка

Установите Node.js 22+ и npm. Заполните `.env` секретами так же, как для Compose. Для запуска Node-процессов вне Docker задайте `DATABASE_URL` на локальный порт PostgreSQL, например `postgres://document_linking:<POSTGRES_PASSWORD>@127.0.0.1:55432/document_linking`; `REDIS_URL` оставьте `redis://127.0.0.1:56379`.

```powershell
npm ci
docker compose up -d postgres redis
npm run migrate
npm run dev:api
```

В отдельных терминалах запустите `npm run dev:worker` и `npm run dev`. Откройте Vite на http://127.0.0.1:5173. API и Worker используют Node-переменные из `.env`; интерфейс передаёт введённый API-токен только в заголовках запросов и не сохраняет его. Идентификатор активного задания хранится в `sessionStorage`, чтобы восстановить прогресс после перезагрузки вкладки.

## Переменные окружения

Полный список и безопасные пустые значения находятся в `.env.example`.

- `POSTGRES_PASSWORD`, `API_BEARER_TOKEN` — обязательные разные production-секреты длиной от 32 символов.
- `POLZA_API_KEY` — опциональный ключ Polza AI; также поддерживается `POLZA_AI_API_KEY`.
- `POSTGRES_DB`, `POSTGRES_USER`, `DATABASE_URL`, `REDIS_URL` — базы и подключения. В Compose URL БД формируется из `POSTGRES_*`; локальным Node-процессам задайте host URL вручную.
- `PORT`, `PG_PORT`, `REDIS_PORT` — порт API и опубликованные host-порты PostgreSQL/Redis.
- `MAX_REQUEST_SIZE_MB` — общий лимит тела HTTP-запроса, по умолчанию 32 МиБ.
- `MAX_DOCUMENT_SIZE_MB` — лимит одного документа, по умолчанию 16 МиБ.
- `MAX_DOCUMENT_SET_SIZE_MB` — суммарный лимит документов после разбора JSON, по умолчанию 30 МиБ.
- `MAX_DOCUMENTS` — число документов в одном комплекте, по умолчанию 100.
- `LLM_MAX_INPUT_TOKENS`, `LLM_MAX_CALLS_PER_RUN`, `LLM_TIMEOUT_MS`, `LLM_MAX_RUN_MS` — ограничения обработки Gemma.

Превышение размера запроса, документа, комплекта или числа документов возвращает HTTP 413 с причиной. Лимиты не отключаются; их значения можно согласованно настроить в указанном порядке: размер документа ≤ комплекта ≤ HTTP-запроса.

## API

Все endpoints, кроме `/api/health`, требуют `Authorization: Bearer <API_BEARER_TOKEN>`.

- `POST /api/linking-jobs` — создать асинхронное задание с `Idempotency-Key`.
- `GET /api/linking-jobs/{id}` — статус, прогресс, токены, стоимость и результат.
- `POST /api/linking-jobs/{id}/resume` — продолжить завершившееся ошибкой задание с сохранённым checkpoint.
- `POST /api/linking-runs` и `GET /api/linking-runs/{id}` — синхронный совместимый API и чтение результата.
- `PATCH /api/linking-runs/{runId}/links/{linkId}` — решение специалиста по связи.
- `GET /api/demo` и `GET /api/health` — примеры и состояние сервиса.

Доступные контракты Structured Extraction 1.2.0 и Document Linking 1.2.0 не менялись. Поля будущих minor-версий Structured Extraction принимаются; несовместимая major-версия диагностируется. Отношения остаются открытыми строками. Программная часть проверяет ссылки на исходные данные, не подменяя семантические решения модели.

Перед анализом движок строит общий реестр всех скалярных значений из входных JSON с уникальными reference ID, исходными путями, значениями, row ID, provenance и контекстом расположения. Gemma выбирает evidence по ID; сервер разрешает его в точный исходный путь и сохраняет совместимый публичный формат доказательств. При технической ошибке Gemma получает исходное предложение и список проблем и может до двух раз исправить ссылки или отозвать связь. Первоначальное предложение и результат исправления остаются в `link_validation_diagnostics`. При сомнении в OCR связь сохраняется только со статусом `review`.

## Повторы и фоновые задания

401/403/402 от Polza и ошибки 4xx не повторяются. Для 429 используется `Retry-After` с ограничением времени ожидания. Сетевые ошибки, таймауты и 5xx используют ограниченный exponential backoff BullMQ. Число попыток ограничено. Прогресс сохраняется в PostgreSQL, а при старте Worker незавершённые задания сверяются с очередью. PostgreSQL lease исключает параллельную обработку одного задания.

## Проверки и CI

```powershell
npm ci
npm test
npm run test:contract
npm run typecheck
npm run build
$env:DATABASE_URL='postgres://document_linking:<password>@127.0.0.1:55432/document_linking'
$env:REDIS_URL='redis://127.0.0.1:56379'
npm run test:integration
docker compose up --build
```

GitHub Actions на каждом push и pull request запускает unit, contract, typecheck, production build, PostgreSQL/Redis integration tests и сборку Docker image. CI не использует ключ Polza и не делает платных запросов к модели.

`npm run test:polza` — отдельный настоящий smoke-запрос, если ключ доступен; `npm run test:polza:full` запускает большой платный прогон. Независимой эталонной разметки нет, поэтому precision, recall и F1 не измерены.

Протокол независимого benchmark и повторные прогоны для оценки стабильности описаны в [`evaluation/README.md`](evaluation/README.md). Разметка должна быть подготовлена экспертами без просмотра ответов модели.
