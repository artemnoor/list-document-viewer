# Сверка КФЗ — Structured Extraction

Веб-приложение первого этапа системы сверки КФЗ: преобразует готовые JSON-результаты Document Parser в нормализованные структурированные данные с provenance до исходного фрагмента. Исходные документы приложение не распознаёт.

## Что работает

- Демонстрационный набор согласованных результатов парсинга: КФЗ, договор, акт, счёт, дополнительное соглашение и реестр.
- Адаптер настоящих форматов Document Parser: `parts`, `model_parts`, `visual_layout`, `logical_tables`, Docling `document.tables`, Office-таблицы и координаты.
- Классификация документа детерминированными признаками с семантической классификацией через LLM для неоднозначных случаев.
- Извлечение реквизитов, дат и периодов, организаций, сумм, количеств, единиц измерения, таблиц и всех проверяемых строк КФЗ.
- Гибридное извлечение: правила для однозначных значений и Polza AI (`deepseek/deepseek-v4-flash`) для классификации, семантических полей и нестандартных заголовков таблиц. Модель получает исходный текст и ячейки со стабильными ID; ответы проходят JSON Schema (с локально валидируемым JSON fallback), проверку исходного текста и проверку ID.
- Нормализация дат, сумм в точные decimal-строки, единиц измерения и идентификаторов; исходные значения сохранены рядом с нормализованными.
- Provenance для извлечённых значений: ID исходного элемента, страница и PDF bbox либо адрес XLSX, текст-источник и уверенность. Нижняя система координат Docling преобразуется в TOPLEFT, исходная система тоже сохраняется.
- Просмотр демонстрационных страниц и таблиц с переходом к источнику, просмотр JSON парсера и результата извлечения, экспорт результата в JSON.
- HTTP API и постоянное хранение результатов через слой Data Storage и базу D1.

## Данные и ограничения

Предзагруженные документы — демонстрационный набор с подготовленным результатом парсинга. В `tests/fixtures/` также лежат исходные JSON-примеры из тестового корпуса `artemnoor/list-document-viewer`, используемые только для тестов адаптера. Можно импортировать JSON парсера (в том числе отдельный `.layout.json` вместе с analysis JSON). Загрузка произвольного PDF/DOCX/XLSX не запускает OCR или Docling.

Для LLM-вызова Worker отправляет ограниченный контекст на `https://polza.ai/api/v1/chat/completions`. Ключ `POLZA_API_KEY` остаётся на сервере и не передаётся браузеру. Временные сетевые ошибки, 429 и 5xx получают ограниченный повтор; коды 401, 402 и 404 возвращаются как диагностируемые ошибки. Если провайдер отклоняет строгий `json_schema`, используется `json_object`, после чего результат всё равно проходит локальную проверку Zod и grounding. Модель не создаёт provenance: принятые значения подтверждаются самим parser result.

Document Linking, финансовая сверка, расчёты, заключения и OCR/Docling не входят в этот этап.

## Оценка Extraction

MVP scorer использует вручную проверенный single-reviewer gold по JSON Schema в `evaluation/mvp-extraction-gold.schema.json`. Gold фиксирует байтовый SHA-256 Parser artifact, `input_hash`, критичные и остальные поля, typed/raw values, source path/provenance и ожидаемые row IDs. Predictions привязываются к каждому repeat через run manifest; manifest и файлы prediction хешируются. Золото и manifest не заполняются из ответов оцениваемой модели.

Запуск из каталога сервиса:

```bash
node scripts/evaluate-mvp-extraction.mjs --gold evaluation/mvp-v1/extraction-gold.json --predictions evaluation/mvp-v1/runs.json --out reports/mvp-extraction-report.json
```

Если сценарий отсутствует, модель завершилась ошибкой, prediction не прошёл схему/хеш-проверку или вернулся `rules_only`, scorer сохраняет его как failed LLM-required и оставляет ожидаемые поля и строки в знаменателях recall. Q1 требует 100% critical field recall и accepted value/source correctness, а также не менее 95% recall остальных полей и строк. N/A остаётся `null`; статус отчёта не становится pass при неприменимом обязательном измерении. Логи не содержат source values или model response text; уровень задаётся через `LOG_LEVEL`.

## Архитектура

| Компонент | Расположение |
| --- | --- |
| Mock Document Parser, совместимый адаптер и демонстрационные результаты | `lib/parser/`, `data/parser-results/` |
| Классификация, схемы, гибридное извлечение и Polza AI | `lib/extraction/` |
| API | `app/api/` |
| Хранение и схема базы данных | `lib/storage.ts`, `db/`, `drizzle/` |
| Пользовательский интерфейс | `app/page.tsx`, `components/` |
| Эталонные проверки | `tests/` |

Frontend и API реализованы на TypeScript/JavaScript; типы выходных данных валидируются расширяемыми Zod-схемами. Источник развёрнут как Vinext-приложение для Cloudflare Workers с D1.

## Локальный запуск

Требуется Node.js `>=22.13.0`.

```bash
npm run install:ci
npm run dev
```

Перед первым локальным запуском D1 примените миграции:

```powershell
npm run db:migrate:local
```

Для production-сборки:

```bash
npm run build
```

Проверки:

```bash
npm test
npm run test:api
npm run test:polza
```

Локальная работа с D1 использует Miniflare. Для локального Worker храните `POLZA_API_KEY=...` в `.dev.vars` (файл исключён Git); для развёрнутого Worker задайте секрет через `wrangler secret put POLZA_API_KEY`. В PowerShell проверьте наличие, не печатая значение: `if ($env:POLZA_API_KEY) { 'POLZA_API_KEY_PRESENT' } else { 'POLZA_API_KEY_MISSING' }`. `npm run test:polza` выполняет один реальный smoke flow: `/models`, одно извлечение в Compare и чтение сохранённого результата из D1; он требует запущенное приложение и ключ, загруженный в Worker.

Локальная авторизация требует явного sign-in и работает только на loopback; middleware удаляет клиентские `oai-authenticated-user-*`. В production произвольные OAI headers не устанавливают личность: Worker принимает только HS256 JWT с проверяемой подписью, issuer, audience и сроком действия. Задайте `AUTH_SESSION_HMAC_SECRET` как Worker secret и `AUTH_SESSION_ISSUER` / `AUTH_SESSION_AUDIENCE` как Worker vars; доверенный hosting слой должен выпускать этот JWT. Без такой проверенной сессии личные документы и операции записи закрыты, а демодокументы остаются публичными только для чтения. Параметры D1 и миграции находятся в `.openai/hosting.json` и `drizzle/`.
