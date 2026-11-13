# Архитектура Phystech Trace

## Границы модулей

| Модуль | Код и ответственность | Хранилище / очередь | HTTP |
| --- | --- | --- | --- |
| Document Parser | Существующий `backend/`: Docling, OCR, нативный разбор PDF/Office, source layout и просмотр страниц | Отдельный volume `parser-uploads`; модели Docling в `parser-models` | `:8081`, Swagger `/docs` |
| Structured Extraction | Импортированный исходный адаптер Document Parser, классификация, rules/Polza extraction, исходные и нормализованные значения | Таблица `trace_extractions` в PostgreSQL | `:8082`, Swagger `/docs` |
| Document Linking | Импортированный LLM resolver, валидация evidence и ручные решения | PostgreSQL и Redis/BullMQ | `:8083`, Swagger `/docs` |
| Gateway | Проекты, загрузка, межсервисная оркестрация, прогресс и повторы этапов | Таблицы `trace_projects`, `trace_documents` в PostgreSQL | `:8084`, Swagger `/docs` |
| Frontend | Vue 3 + TypeScript + Vite; показывает результаты API и отправляет решения специалиста | Нет локальной бизнес-логики или хранения документов | `:8080` |

Сервисы находятся в одной Compose-сети. Каждый исходный модуль запускается отдельным контейнером и сохраняет свою ответственность. Parser остаётся в существующем `backend/`, чтобы не менять его публичные пути и локальный интерфейс; Dockerfile и OpenAPI отдельного Parser API находятся в `services/document-parser/`.

Gateway управляет стадиями Parser → Extraction → Linking. Состояние каждого этапа и промежуточные результаты записываются до перехода дальше. После перезапуска Gateway восстанавливает незавершённые проекты. Повтор этапа пропускает уже сохранённые результаты ранних стадий. Linking сохраняет BullMQ checkpoints и возобновляет ошибочное задание.

PostgreSQL — общее постоянное хранилище результатов. Redis используется очередью Linking; Gateway не копирует алгоритм очереди. Parser сохраняет оригиналы и OCR-кеш на отдельном volume. Система не требует Cloudflare Workers, D1, ChatGPT или Cloudflare инфраструктуры.

## Внешняя модель и данные

Parser контейнеру ключ Polza не передаётся; его Polza review отключён. Новый проект по умолчанию помечается `confidential`, а внешняя модель запрещена. Разрешение доступно только для `public`, `synthetic` или `anonymized`. Gateway проверяет эту политику, а Linking API в Compose требует и класс данных, и явное согласие. Наличие ключа само по себе не отправляет данные.

## Сеть и доступ

Пользовательские порты привязаны к `127.0.0.1`. PostgreSQL, Redis и Linking worker наружу не публикуются. Linking API защищён bearer token. Для загрузки ресурсов Swagger UI браузеру нужен доступ к `unpkg.com`.
