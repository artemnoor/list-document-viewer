# Явная граница доступа к Document Parser

[Индекс](00-index.md) · [План, ранний коммит C02](../../.ai-factory/PLAN.md)

Срез: 2e6da4b2. Это проект изменения, не выполненное исправление.

## Подтверждение и минимальное решение

В [backend/server.py](../../backend/server.py) Handler.check_origin разрешает запрос без Origin. do_GET/do_POST/do_DELETE проверяют Origin, но не личность/межсервисный credential. В [Compose](../../phystech-trace/docker-compose.yml) Parser опубликован на localhost:8081. Loopback и CORS не являются проверкой права на содержимое.

Для MVP одновременно:

1. Убрать публикацию Parser data port в обычном интеграционном Compose; сохранить внутренний PARSER_URL = http://document-parser:18765.
2. Добавить единый fail-closed service-auth guard до чтения тела/маршрутизации в Parser. Независимо запущенный сервис тоже защищён, а не только скрыт портом.
3. Настроить отдельный внутренний секрет через env/file для Parser и Gateway. Gateway добавляет его ко всем Parser requests: upload, analysis polling, retry, source и pages. Не использовать для браузера или вместо пользовательской auth.
4. Gateway проверяет local user/project_document membership перед source/page/result proxy. Parser остаётся общим внутренним техническим хранилищем, и его service token не является пользовательским ACL.
5. Health и минимальные метаданные docs/spec можно выделить в явный allowlist без содержимого документов; остальные неизвестные data paths не открывать по умолчанию.
6. Диагностическая публикация порта — opt-in профиль с той же аутентификацией, а не обход guard.

## Матрица прямых endpoints

Маршруты взяты из текущего server.py; отдельного /original нет, оригинальные байты отдаёт /source.

| Метод и маршрут | Данные/эффект | Без service credential | Gateway |
| --- | --- | --- | --- |
| GET /api/documents | Список и metadata | 401/403, без списка | Только нужные scoped операции, общий список наружу не проксировать |
| GET /api/documents/{id} | Представление/текст источника (в зависимости от формата), не только metadata | 401/403 | После project membership |
| GET /api/documents/{id}/source | Оригинальные байты | 401/403, без байтов | Авторизованный source proxy |
| GET /api/documents/{id}/content | Производное содержимое | 401/403 | Не создавать обходной публичный proxy |
| GET /api/documents/{id}/analysis | Полный Parser JSON/статус | 401/403 | Внутренний polling; пользователю только scoped result |
| GET /api/documents/{id}/pages/{page} | Изображение страницы | 401/403, без preview | Авторизованный page proxy |
| POST /api/documents | Загрузка | Отказ до body/save/job creation | После local auth и проверки active run |
| POST /api/documents/{id}/retry | Повтор OCR | Отказ без нового job | По политике run и membership |
| POST /api/documents/{id}/document-review/accept-all | Изменение распознавания | Отказ без изменений | Не публиковать новый маршрут без явного project/revision контракта |
| POST /api/documents/{id}/document-review/{suggestion}/{accept,reject,undo} | Изменение результата | Отказ без изменений | Аналогично; новый Parser artifact инвалидирует downstream |
| DELETE /api/documents/{id} | Удаление общего файла/JSON | Отказ без удаления | Не разрешать из проекта без учёта других memberships |
| GET /health | Техническая готовность | Можно разрешить allowlist | Сохраняет работу container healthcheck |
| GET /docs, /openapi.json | Описание API | Явная отдельная policy | Ни assets, ни Try it out не содержат service secret |

Для неправильного формата/отсутствия secret guard не должен сначала раскрывать существование конкретного документа. Не логировать токены, имена/текст/байты источников.

## Файлы будущего изменения

- Существующие: backend/server.py; phystech-trace/gateway/main.py; phystech-trace/docker-compose.yml; phystech-trace/services/document-parser/openapi.json; backend/tests/test_server_audit.py.
- Новые: backend/tests/test_parser_internal_auth.py; phystech-trace/tests/e2e/parser_access.py.
- При добавлении локальной пользовательской сессии: phystech-trace/frontend/src/api.ts, App.vue и Gateway; это не заменяет внутреннюю защиту Parser.
- Миграции для самого service guard не нужны. Project membership/immutable snapshots развиваются после первого модельного цикла; direct endpoints до этого остаются закрытыми.

## Проверки и критерий завершения

- Для всех методов выше: missing/wrong token, без Origin и с разрешённым Origin → запрет. Неверный Origin сам по себе не считается основным security test.
- Правильный внутренний credential позволяет Gateway пройти Parser upload/analysis/source/page, а browser credentials не принимаются Parser как service credential.
- Rejected upload/retry/review/delete не меняют files/jobs/analysis. Healthcheck работает без обхода data guard.
- В default Compose host:8081 недоступен, но document-parser:18765 доступен Gateway. В opt-in diagnostic profile прямые data requests требуют credential.
- Без обязательного секрета интеграционный режим не стартует. Старые standalone Parser tests адаптируются к явно объявленному режиму; не оставлять тихий unauthenticated fallback.
- Эти тесты входят в раннюю минимальную защиту до работы с моделью на комплектах; дальнейший project ACL/recovery не блокирует исследование bounded Linker на immutable fixtures.

