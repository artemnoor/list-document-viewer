# Источники, методика и границы проверки

[Общий индекс](00-index.md)

Дата: 13.11.2026. Проверенный HEAD: `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.

## Фактически выполненное исследование

- Проверены рабочая ветка, полный HEAD и статус Git. До начала существовал один незакоммиченный файл `docs/phystech-trace-remediation-plan.md`; его содержимое прочитано, файл не изменялся.
- Прочитаны/исследованы Gateway, standalone Extraction runtime, LLM extraction context/grounding, Linking matcher/worker/migrations, Vue App/EvidencePanel, Compose/Dockerfile, контрактные тесты и evaluation protocol.
- Прочитаны интеграционный отчёт, полный неуспешный E2E, compact результаты по документации, предыдущий live Linking report и проектная заметка о качестве Parser.
- `git ls-files backend/uploads` показал 116 tracked файлов; проверка не классифицировала содержание/конфиденциальность.
- `git ls-files .github/workflows/* **/.github/workflows/*` обнаружил workflow только внутри импортированного Linking.
- Найдены фактически отдаваемая Parser OpenAPI и её servers.url, подтверждён CDN также у Parser.
- Созданы только Markdown-документы данного комплекта. Исследование не выполняло OCR, Docker up/down, live LLM, перезапусков, миграций, удаления файлов, очистки истории, commit или push.

Использован исследовательский подход `aif-explore`; пользователь прямо запросил документы по каждому пункту, поэтому результат разнесён по карточкам, а не ограничен одной общей запиской. Имена и номера проблем соответствуют переданному аудиту.

## Первичные локальные источники

| Источник | Для каких выводов использован |
| --- | --- |
| [Gateway](../../phystech-trace/gateway/main.py) | routes/ACL, COALESCE, upload/start/retry, повторное чтение документов, quality gate, health и resume |
| [Extraction runtime](../../phystech-trace/services/structured-extraction/runtime/server.mjs) | прямой доступ, client policy, input_hash/input_version, MAX+1 и UNIQUE, storage |
| [LLM Extraction](../../phystech-trace/services/structured-extraction/lib/extraction/polza-ai.mjs) | budget/sample context, source IDs, validateGrounding и причины отказа |
| [Linking matcher](../../phystech-trace/services/document-linking/src/linking/llm-matcher.ts) | фрагментация, финальный context, checkpoints, correction и учёт usage |
| [Linking worker](../../phystech-trace/services/document-linking/server/worker.ts) | существующие BullMQ/claim/lease/heartbeat/recovery |
| [Linking migrations](../../phystech-trace/services/document-linking/server/migrate.ts) | существующий отдельный runner и advisory transaction lock |
| [Vue App](../../phystech-trace/frontend/src/App.vue) | array paths, slice 32, isReviewable и UI |
| [EvidencePanel](../../phystech-trace/frontend/src/components/EvidencePanel.vue) | отображение PDF/XLSX источников и отсутствие worksheet grid |
| [Compose](../../phystech-trace/docker-compose.yml) | port mapping, development, defaults, worker PID probe |
| [Gateway Dockerfile](../../phystech-trace/gateway/Dockerfile) | текущая HTTP healthcheck |
| [Parser OpenAPI](../../phystech-trace/services/document-parser/openapi.json), [Parser HTTP server](../../backend/server.py) | фактически отдаваемый servers.url, Swagger CDN |
| [Контрактные тесты](../../phystech-trace/tests/contracts/test_contracts.py) | фактический охват семи проверок |
| [Evaluation README](../../phystech-trace/services/document-linking/evaluation/README.md) | существующие scorer/packets; незавершённый независимый gold |
| [Интеграционный отчёт](../../phystech-trace/docs/integration-report.md) | предыдущие тесты, rules_only и полный/compact Linking |
| [Full-set failure](../../phystech-trace/tests/e2e/results/full-set-live-attempt.json) | сохранённый пятидокументный retry failure |
| [Live Linking report](../../phystech-trace/services/document-linking/reports/polza-live-check-2026-11-13.md) | исторический разброс 0–2; отдельно final-code наблюдения |
| [Уроки Parser-аудита](../../.ai-factory/patches/2026-11-11-document-corpus-audit.md) | ready не означает качество, сохранение native structures и приватного корпуса |

Карточки содержат более точные точки изменения. Ссылки ведут в текущий checkout; после изменения кода исходный baseline восстанавливается через указанный commit. Числа из старых отчётов не выдаются за результаты новых прогонов.

## Внешние первичные источники

Проверены доступные официальные страницы. Они подтверждают общие свойства механизмов; выбор дизайна и его применение к Phystech Trace — предложение данного исследования.

- [PostgreSQL 16: INSERT, ON CONFLICT, RETURNING](https://www.postgresql.org/docs/16/sql-insert.html). ON CONFLICT DO UPDATE обеспечивает атомарный исход insert/update; это основание варианта counter row в №11. Полную транзакционность сохранения payload и идемпотентность всё равно нужно реализовать и проверить.
- [PostgreSQL 16: явные блокировки](https://www.postgresql.org/docs/16/explicit-locking.html). Документация различает row-level и advisory locks; scope/время жизни выбранной блокировки должны соответствовать владению соединением и run в №13/20.
- [BullMQ: idempotent jobs](https://docs.bullmq.io/patterns/idempotent-jobs). Идемпотентность означает одинаковый итог после повтора; сложные side effects лучше разбивать на понятные атомарные шаги. Для №13/14 это не обещание exactly-once внешнего LLM.

Попытки получить страницы OWASP API1 и FastAPI background tasks вернули ошибки доступа, поэтому их содержание не использовано как проверенное внешнее доказательство. Технические свойства безопасности в карточках основаны на обнаруженных маршрутах и явно предложенной модели прав, а не на приписанной этим страницам цитате. Веб-поиск не дал результатов до прерывания; официальные страницы выше прочитаны прямыми HTTPS-запросами. Дополнительные пакеты для исследования не устанавливались.

## Как проверять комплект перед использованием

1. Карточки 01–35 существуют и по одной соответствуют исходной нумерации.
2. В каждой есть статус доказательств, причина, конкретное предлагаемое решение, будущие шаги, тесты, критерий закрытия и ограничения.
3. Все локальные Markdown-ссылки указывают на существующие файлы/каталоги; нет потери dependencies.
4. Не объявлены выполненными ни исправления, ни новые runtime/live тесты. Стабильность финальной версии, гонки и security exploit остаются отдельной будущей проверкой.
5. Новые поля/таблицы/статусы описаны как дизайн; совместимость с 1.2.0 ещё предстоит обеспечить.
6. Общая модель и карточки не противоречат друг другу: current result требует manifest/revision, source evidence — immutable artifact, human decision — отдельный аудит.
7. `git diff --name-only` для tracked файлов пуст; все документы, созданные данным исследованием, находятся в `docs/phystech-trace-remediation/`. Изначальный общий план не входит в созданный комплект. При заключительной проверке также появился untracked `.ai-factory/RESEARCH.md`; он не создан и не изменён данным исследованием, его происхождение не устанавливалось, в комплект и проверку согласованности он не включён.

## Историческая проверка после первой пользовательской оценки

Во всех 35 карточках указан пользовательский вердикт и объём MVP. В 15 карточках добавлены минимальные решение/шаги/проверки и критерии приёмки, исходный расширенный дизайн явно обозначен как будущий. В остальных карточках и индексе устранены скрытые обязательства по распределённому исполнению, confidential E2E и расширенной telemetry. Базовые scope и ограничения источников не изменены.

Проверены 38 Markdown-файлов, 35 карточек и 35 строк индекса; локальные ссылки разрешаются, в таблице вердиктов четыре столбца. Повторный независимый read-only Research Coherence Gate — PASS: summary, карточки и очередность согласованы, actionable discrepancies не найдены. Эта проверка относится только к документам; исправления, новые runtime/live тесты, commit/push не выполнялись. Tracked diff остаётся пустым.

## Текущая редакция: шесть замечаний, единый план и Q1

Добавлены документы38/39 и .ai-factory/PLAN.md; обновлены02/05/33/36 и индекс. В пределах комплекта теперь40 Markdown документов и единый план отдельно:41 проверяемый артефакт. План имеет24 открытые implementation-задачи по коммитам с файлами/миграциями/проверками/условиями завершения и отдельно отмеченное согласование Q1. Baseline и application/model tests не запускались; пользователь потребовал согласовать их отдельно.

Дополнительно статически сверены Parser do_GET/do_POST/do_DELETE, per-provider send boundaries, annotation compiler/schema и Linking scorer. Подтверждено: проверка Origin не аутентифицирует; single-reviewer mode пока требует реализации; quality scorer считает только первый repeat. Эти факты не выдаются за воспроизведённые runtime дефекты.

Независимый read-only разбор выявил две неявные задачи: per-send policy context и исполнение/подсчёт Extraction baseline. В плане добавлены точные resolver/hook файлы и отдельный C03b, а в C05 runner/scoring interfaces; также уточнено, что Parser GET/{id} может возвращать текст/представление источника. По содержанию повторная проверка прошла; замечание оформления таблицы исправлено и проверено структурно.

Автоматическая проверка только документов:41 файл,24 задачи совпадают с24 строками commit plan, локальные ссылки и столбцы таблиц корректны. SHA256 предварительно утверждённого Q1 сохранён и совпадает с PLAN; research summary snapshot/hash также совпадает. Tracked code/config diff пуст; никакие тесты приложения, модели, Docker, миграции или реальные commits не выполнялись.

## Ограничения выводов

Итог первоначальной проверки артефактов до пользовательской переоценки scope: 38 Markdown-файлов, ровно 35 карточек 01–35; обязательные разделы присутствовали, неразрешённых локальных ссылок и ошибок UTF-8 не обнаружено. Первоначальный независимый read-only review индекса и документов 01–37 прошёл Research Coherence Gate: PASS; actionable discrepancies не найдены. Этот исторический результат не заменяет проверку обновлённой редакции и не является приёмкой реализации.

Разбор кода не устанавливает качество на реальных финансовых документах, не подтверждает фактическую утечку данных и не заменяет независимую разметку. Для каждого риска в карточках дан способ воспроизведения и измерения после разрешения реализации. Внешние ресурсы — эксперты, IdP, approved internal provider и публикационные разрешения — остаются явно указанными зависимостями.

