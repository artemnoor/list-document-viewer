# Исполняемый план: стабильный локальный MVP Phystech Trace

Branch: feat/phystech-trace-integration
Created: 2026-11-13
Baseline commit: 2e6da4b2b3b57b5c4e9137d8657770beba65ffdf
Статус: только план; все implementation checkboxes открыты. Создание этого документа не разрешает исправления, LLM-запуски, commit/push или публикацию.

## Original Request

## Что я всё ещё считаю недостатками

|   |
| - |

Приоритет

|   |
| - |

Замечание

|   |
| - |

Что изменить

|   |
| - |

Высокий

|   |
| - |

Первые два больших этапа посвящены инфраструктуре, а нестабильный Linking исправляется только на третьем

|   |
| - |

После фиксации baseline и минимальной защиты данных быстрее переходить к №01, 03 и 15

|   |
| - |

Высокий

|   |
| - |

Защита прямого доступа к Parser не выделена достаточно явно

|   |
| - |

Защитить или скрыть прямые endpoints Parser, включая оригиналы и результаты распознавания, а не только Gateway и Extraction

|   |
| - |

Высокий

|   |
| - |

Нет утверждённых числовых критериев качества

|   |
| - |

До оптимизации зафиксировать baseline, допустимые ошибки, пороги качества и тестовые лимиты

|   |
| - |

Средний

|   |
| - |

План №33 предполагает двух независимых экспертов

|   |
| - |

Для ближайшего MVP начать с небольшого вручную проверенного эталона; вторую разметку и арбитраж добавить при расширении

|   |
| - |

Средний

|   |
| - |

Нет единого исполняемого плана с точными изменениями по коммитам

|   |
| - |

Перед разработкой разложить работу на небольшие задачи с конкретными файлами, миграциями, тестами и условиями завершения

|   |
| - |

Средний

|   |
| - |

Предметный план №36 остался без изменений

|   |
| - |

После стабилизации интеграции отдельно спроектировать финансовые расчёты, ОСВ и сверку КФЗ

## Settings

- Testing: yes — targeted regression/contract/HTTP/mock E2E; live только отдельным согласованным запуском.
- Logging: standard — каждый task ниже имеет события/уровни; LOG_LEVEL регулируется без правки кода.
- Docs: yes — README/data-flow/contracts обновляются в том коммите, где изменяется соответствующий контракт или способ запуска.
- Scope: один локальный principal и один Gateway process; разрешённый тестовый корпус; confidential blocked.
- Git: существующая ветка, без checkout/worktree/автоматического commit.
- Путь: .ai-factory/PLAN.md — единый checklist и порядок реализации; карточки docs/phystech-trace-remediation/01–35 — обоснование, не независимые очереди.
- Новые файлы ниже явно отмечены; их команды/пути тестов станут исполнимы только после соответствующего коммита. Сейчас эти файлы не созданы.
- Вне scope: IdP/RBAC, distributed Gateway queue/lease/fencing, object storage/GC, financial budget ledger, advanced viewers, полный chaos/conformance suite.

## Research Context

Source: `docs/phystech-trace-remediation/00-index.md` (Active Summary, Updated: 2026-11-13, SHA256: 2e1821550508b72b90985a31cf71e1f2bfab2c8f6c5fab93bd9cec91dc3bdf21)

Это выбранный актуальный исследовательский источник данного комплекта; внешний `.ai-factory/RESEARCH.md` не использовался и не изменялся. Ниже сохранён snapshot текущего Active Summary для проверки drift; более позднее прямое указание пользователя имеет приоритет.

Topic: Стабильный локальный MVP Phystech Trace, 35 замечаний и шесть последующих уточнений пользователя.
Цель: ранний bounded Linking/grounded Extraction/repair после честного baseline и минимального периметра.
Ограничения: только документы; код, конфигурация и БД не менялись. Пользователь предварительно утвердил Q1; запуск application/model tests согласуется отдельно, сейчас не разрешён.
Порядок: C01–C03 измеритель/малый single-reviewer gold/ранний CI; C04a–c прямой Parser/Extraction периметр и local auth; C05 frozen measured baseline; C06–C09 немедленно №01/15/03; затем C10–C21 integrity/UI/recovery/E2E.
Измерения: Q1 предварительно утверждён 13.11.2026 20:35 МСК; P≥.95, R≥.90, F1≥.92, rowP/R≥.90, evidence/coverage100%, Jaccard mean≥.90/min≥.80, 6 комплектов×5 повторов и limits из38. Реальный baseline не измерен; gold и критичные поля должен проверить человек до predictions.
Периметр: Parser source/content/analysis/pages/list/upload/retry/review/delete закрыты внутренним guard и private port в будущей C04a; это план, не уже выполненная защита.
Архитектура MVP: существующие PostgreSQL/files, project scope, immutable snapshots/manifest, один Gateway, ресурсные counters; enterprise storage/IdP/queue/ledger отложены.
После стабилизации: отдельные design tasks D01–D05 из36 для ОСВ, финансовых расчётов, периодов и сверки КФЗ. Формулы и financial tolerance не выдумывать.
Единый план: .ai-factory/PLAN.md — точные коммиты, файлы, миграции, тесты, logging и completion criteria; все implementation tasks открыты.
Открыто: ручной gold, критичные поля, measured baseline, назначение владельцев, публикационные права, тестовый execution/exposure. Второй разметчик/арбитр не обязательны для ближайшего MVP.

## Requirements Reconciliation

Authority: последнее пользовательское замечание уточняет предыдущую оценку 35 планов; затем актуальные scope карточек и индекс; расширенные варианты — справочные. Числовая редакция Q1 предварительно утверждена пользователем 13.11.2026 20:35 МСК; запуск тестов и live exposure согласуются отдельно. Старые правила двухэкспертной разметки сохраняются только для расширенного режима.

| Решение | Источник | Проверка/задачи |
| --- | --- | --- |
| Baseline и минимальная защита → сразу модели | Последнее сообщение; индекс, новая очередь | C02–C05 до C06; C06–C09 до основной схемы C10 |
| Parser data endpoints защищены отдельно | [Матрица Parser](../docs/phystech-trace-remediation/39-parser-access-boundary.md) | C04a: все GET/POST/DELETE, source/analysis/pages и side effects |
| Числа, ошибки и лимиты до оптимизации | [Предварительно утверждённый Q1](../docs/phystech-trace-remediation/38-quality-gates.md) | Q0 до C05; measured baseline до C06–C09 |
| Один человек вручную проверяет небольшой эталон | Карточка33; source predictions hidden | C02/C05; single-reviewer честно маркирован, gold не создаётся LLM |
| Минимальное хранение и процесс | Предыдущая оценка 4/8/10/13/16 | C10–C14, без enterprise подсистем |
| КФЗ/ОСВ после стабильной интеграции | [Предметный план36](../docs/phystech-trace-remediation/36-kfz-product-scope.md) | Gate C21, затем отдельное предметное проектирование; не обязательный predecessor Linking |

### Поддерживаемые комбинации

| Вход/состояние | Допуск и сохранение | Ответ/side effect | Проверка |
| --- | --- | --- | --- |
| User без сессии × Gateway data route | Не читать source/project data | 401/403, без действия | C04b |
| Service без secret × Parser source/analysis/mutation | Отказ до чтения body/хранилища | Ноль байтов/изменений; info allowlist отдельно | C04a |
| Confidential или нет серверного согласия × внешний provider | Policy denial, visible blocked | Ноль внешних send | C04c/C21 |
| Разрешённый project × spoof flags | Только текущая server policy | Клиентский allow=true не расширяет доступ | C04c |
| Active run × upload/retry | Run snapshot не меняется | Upload409; retry идемпотентен/409 | C12 |
| Ready Parser × partial/stale/unconfirmed critical source | Limited/review/blocked по policy | Нет неограниченного completed | C13 |
| Wrong hash/current revision × resume/publication | История допустима, current не меняется | Resume rejection/conditional update fail | C12 |
| Malformed fragment × remaining budget | Bounded repair только этого fragment | Evidence проверяется; failed при исчерпании | C08/C14 |
| Confirmed machine × not_reviewed | Человек вправе проверить | Не human_confirmed до человеческого действия | C16 |
| Budget/cancel/restart × следующий request | Сохраняемые counters/stop | Нет нового send после запрета | C14/C18 |
| Явно отрицательный/ambiguous/positive gold | Разные denominators и outcome gates | Никаких empty-graph shortcuts | C03/C05/C21 |

Представительный существующий fixture: `phystech-trace/services/structured-extraction/tests/fixtures/document-parser-native-xlsx.analysis.json` через schema/round-trip/evidence. Компактный и широкий сохранённые E2E наборы включаются в frozen corpus после проверки источников/публикационных прав; файлы из backend/uploads не считаются автоматически разрешёнными fixtures.

## Gate Q0: что стопорит оптимизацию

- [ ] Q0.1 Один человек назначен, gold проверен без model predictions, hashes и критичные поля зафиксированы.
- [x] Q0.2 Пользователь предварительно утвердил Q1: 13.11.2026 20:35 МСК, ответ «Утвердить Q1; запуск тестов согласуем отдельно». Это согласование параметров, не реализации или запусков.
- [ ] Q0.3 Scorers исправлены C03/C03b; baseline реально снят C05 на согласованном корпусе/лимитах.
- [ ] Q0.4 Минимальный периметр C04a–c закрывает Gateway, Parser и Extraction; модельная работа использует immutable разрешённые snapshots.
- [ ] Q0.5 Отдельно согласован запуск application/model tests; для live дополнительно подтверждены доступ/расход/exposure и безопасное сохранение результатов. Сейчас не согласован; наличие ключа не считается разрешением.

Эти gates не блокируют завершение самого плана и безопасную подготовку измерителя/корпуса. В этом документе утверждение Q1 зафиксировано, но baseline, ручной gold, реализация и разрешение тестовых запусков не отмечены выполненными.

## Commit Plan

Каждая задача ниже — отдельный предлагаемый коммит с конкретной границей проверки. Commit subjects — предложения, реальные commits здесь не создавались.

| Очередь | Коммит | Ключевая граница |
| --- | --- | --- |
| C01 | `ci: add integration unit contract and build checks` | нет |
| C02 | `feat(evaluation): support single-reviewer MVP gold` | нет; C01 может выполняться независимо |
| C03 | `fix(evaluation): score every repeat against frozen gold` | C02 |
| C03b | `test(extraction): add exact-value baseline scorer` | C02, C03 |
| C04a | `fix(parser): protect all direct document endpoints` | нет; завершить до C05 |
| C04b | `feat(gateway): add minimal local authentication` | C04a для интеграционной проверки |
| C04c | `fix(extraction): enforce trusted external processing policy` | C04a, C04b |
| C05 | `test(evaluation): freeze MVP gold and baseline` | C02, C03, C03b, C04a–c; Q0.1 labels, Q0.2 параметры, Q0.5 разрешение запуска |
| C06 | `feat(linking): plan bounded tasks with complete source coverage` | C05 |
| C07 | `fix(linking): merge bounded results without full-set LLM reduce` | C06 |
| C08 | `fix(linking): recover malformed fragments with bounded retries` | C06, C07 |
| C09 | `fix(extraction): ground staged LLM mappings in exact parser values` | C05; после C08 в основной очереди, можно независимую работу без нарушения baseline |
| C10 | `feat(storage): migrate minimal run manifests and project scope` | C04a–c; в основной очереди после C09 |
| C11 | `fix(extraction): scope history cache and atomic versions` | C10 |
| C12 | `fix(gateway): snapshot active inputs and invalidate stale results` | C10, C11 |
| C13 | `fix(pipeline): gate parser quality and explicit coverage` | C09, C12 |
| C14 | `feat(pipeline): enforce persistent limits and cancellation` | C08, C09, C12 |
| C15 | `fix(ui): resolve evidence paths against exact source snapshots` | C12, C13 |
| C16 | `fix(review): separate machine acceptance from human decisions` | C04b, C12, C15 |
| C17 | `fix(health): expose real readiness and basic queue status` | C04a–c, C12 |
| C18 | `test(recovery): cover basic restart and persistence cases` | C11–C14, C17 |
| C19 | `fix(docs): use correct parser origin and basic API smoke` | C04a, C17 |
| C20 | `test(repository): audit runtime documents and prevent new uploads` | аудит начинается сразу; исправления после подтверждённой классификации |
| C21 | `test(e2e): enforce MVP quality and representative mock pipeline` | C06–C19, C20 по результатам аудита; C01 для CI |

Первый модельный цикл C06–C09 идёт сразу после измерений и короткого пакета C04a–c. Полноценные миграции/project storage/recovery C10+ не служат предварительным условием улучшения Linking на frozen inputs. Однако MVP не принимается, пока данные/изолированность и E2E не доведены до C21.

C01 может выполняться независимо с начала работы; аудит C20 начинается сразу, его разрешённые изменения фиксируются после классификации. Остальные зависимые изменения выполняются последовательно. Если task невозможно закончить за одну сессию, разбить его на два коммита до реализации, сохранив те же явные checks; не прятать невыполненную часть под «готово».

## Tasks

### Подготовка и минимальный периметр

- [x] **C01 — ci: add integration unit contract and build checks** — Workflow создан; в GitHub не исполнен (push/PR не выполнялись).

  Зависимости: нет. Замечания: 35, 27.

  **Изменение:** Создать root workflow на push/PR: backend unittest, Extraction unit, Linking unit/typecheck/build, Vue typecheck/build, shared contracts. Не включать live secrets и не считать skipped обязательный job успешным; mock E2E подключается в C21.

  **Файлы:** `.github/workflows/integration.yml (новый)`; `phystech-trace/services/document-linking/package.json`; `phystech-trace/frontend/package.json`.

  **Миграции:** нет.

  **Проверка:** Из чистого runner выполнить существующие scripts: python -m unittest discover -s backend/tests; python -m unittest discover -s phystech-trace/tests/contracts -v; npm test в обоих сервисах; npm run build Linking; npm run typecheck/build Vue. Перечислить реально пропущенные integration/live tests.

  **Готово, когда:** Workflow реально отработал либо явно помечен «не исполнен в GitHub». YAML сам по себе не закрывает №35.

  **Логи:** CI job/status и безопасные summaries; не публиковать uploads, credentials и raw model responses. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [x] **C02 — feat(evaluation): support single-reviewer MVP gold** — Single-reviewer compiler added; tests authored but not executed (Q0.5 approval pending).

  Зависимости: нет; C01 может выполняться независимо. Замечания: 33.

  **Изменение:** Ввести явно названный MVP single-reviewer mode: один человек завершает разметку всех пар/строк/evidence до predictions. Сохранить source hashes, required coverage, checked raw values, ambiguity и identity. Не требовать обязательных трёх identities, как текущий compiler. Старый двухэкспертный mode оставить для будущего расширения; не помечать single-reviewer как adjudicated двумя людьми.

  **Файлы:** `phystech-trace/services/document-linking/scripts/prepare-annotation-packets.ts`; `phystech-trace/services/document-linking/scripts/compile-expert-annotations.ts`; `phystech-trace/services/document-linking/evaluation/annotations.schema.json`; `phystech-trace/services/document-linking/evaluation/README.md`; `phystech-trace/services/document-linking/tests/annotation-packets.test.ts`.

  **Миграции:** нет; version/mode только annotation artifacts.

  **Проверка:** Добавить tests single completed packet, pending rejection, missing pair, invalid source hash/path/value, invalid reviewer identity. Existing three-identity mode остаётся проверяемым.

  **Готово, когда:** Один реальный человек может сформировать валидный frozen MVP gold; сами labels не генерируются агентом из предсказаний.

  **Логи:** Gold version/hash/review mode и validation error codes, без содержимого финансовых документов. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [x] **C03 — fix(evaluation): score every repeat against frozen gold** — Per-repeat scorer and validation added; metric fixtures authored but not executed (Q0.5 approval pending).

  Зависимости: C02. Замечания: 2, 33.

  **Изменение:** Вынести scoreRun/aggregate с отчётом для каждого повтора. Устранить confirmed gaps: сейчас quality только results[0]; evidence сравнивается со всеми gold refs; row scoring учитывает не все структуры. Валидировать annotations/predictions/hash; различать doc relation identity и row instance; paired evidence сопоставлять только своему TP, negatives и ambiguous оценивать по Q1. N/A сохранять, malformed {} не считать успешным пустым графом.

  **Файлы:** `phystech-trace/services/document-linking/scripts/evaluate-links.ts`; `phystech-trace/services/document-linking/tests/evaluation-metrics.test.ts (новый)`; `phystech-trace/services/document-linking/evaluation/README.md`.

  **Миграции:** нет.

  **Проверка:** Ручные счётные fixtures: второй run хуже первого; reverse direction; две строки одной пары; crossed evidence; missing/extra/duplicate; ambiguous/negative; bad schema/hash. Проверить точные TP/FP/FN и worst-repeat gates.

  **Готово, когда:** Ожидаемые числа на ручных fixtures совпадают; каждый repeat влияет на качество, usage unknown сохраняется. Только после этого разрешено записывать baseline.

  **Логи:** Scenario/run IDs, denominator counts и validation failures; model response texts в CI не выводить. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [x] **C03b — test(extraction): add exact-value baseline scorer** — Gold schema, hash-grounded per-repeat scorer and CLI added; counted fixtures authored but not executed (Q0.5 approval pending).

  Зависимости: C02, C03 для общей формы per-repeat отчёта. Замечания: 03, 33.

  **Изменение:** Добавить отдельный Extraction gold/scoreRun: artifact/source hash, список expected fields с critical флагом, raw/typed value, source path/provenance, expected row IDs и факт llm_assisted. Считать critical/noncritical field recall, row recall, exact accepted-value/source correctness по каждому repeat. Fallback rules_only и invalid/missing result — failed LLM-required, не пустой правильный ответ. Существующий rules-only tests/quality-metrics.test.mjs сохраняется, но не заменяет этот scorer.

  **Файлы:** `phystech-trace/services/structured-extraction/evaluation/mvp-extraction-gold.schema.json (новый)`; `phystech-trace/services/structured-extraction/lib/evaluation/mvp-quality.mjs (новый)`; `phystech-trace/services/structured-extraction/scripts/evaluate-mvp-extraction.mjs (новый)`; `phystech-trace/services/structured-extraction/tests/mvp-quality.test.mjs (новый)`; `phystech-trace/services/structured-extraction/tests/quality-metrics.test.mjs`.

  **Миграции:** нет; это schema измерений, не runtime storage.

  **Проверка:** Ручные counted fixtures: missing critical field, неверное raw/source при совпавшем normalized value, duplicate/omitted row, unknown/noncritical, forged provenance, bad hash, failed model и fallback. Точные denominator counts/N/A и Q1 gates проверяются без LLM.

  **Готово, когда:** Есть исполнимый CLI `node scripts/evaluate-mvp-extraction.mjs --gold evaluation/mvp-v1/extraction-gold.json --predictions <run-manifest.json> --out <report.json>`; каждый repeat имеет field/row/source metrics, а fail модели не теряется. Флаги/пути planned, сейчас CLI не создан и не запускался.

  **Логи:** INFO — IDs/counts/review mode; WARN/ERROR — schema/hash/model failure. LOG_LEVEL регулируется; values/source text/secret в общий лог не выводятся.

- [ ] **C04a — fix(parser): protect all direct document endpoints**

  Зависимости: нет; завершить до C05. Замечания: 4, 5, 8 — явное расширение на Parser.

  **Изменение:** Единый fail-closed service guard в GET/POST/DELETE до data access/body read. Отдельный secret Parser↔Gateway, все Gateway Parser callers добавляют credential. Убрать default публикацию 8081, docs/debug opt-in тоже защищены. Матрица 39-parser-access-boundary.md включает source/content/analysis/pages/list/upload/retry/review/delete; /health разрешён отдельным allowlist.

  **Файлы:** `backend/server.py`; `backend/tests/test_parser_internal_auth.py (новый)`; `backend/tests/test_server_audit.py`; `phystech-trace/gateway/main.py`; `phystech-trace/docker-compose.yml`; `phystech-trace/services/document-parser/openapi.json`.

  **Миграции:** нет.

  **Проверка:** Backend auth test на все endpoints без/с неверным token и без/с разрешённым Origin; rejected mutations без side effect. Compose: host port закрыт, Gateway upload/source/page работают, healthcheck не сломан.

  **Готово, когда:** Ни оригинальные байты, ни распознавание, ни previews доступны прямым анонимным запросом. Скрытие порта не заменяет guard standalone Parser.

  **Логи:** Method/route category/auth result; запретить токены, имена/байты документа и неизвестные query parameters. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C04b — feat(gateway): add minimal local authentication**

  Зависимости: C04a для интеграционной проверки. Замечания: 4 — упрощённо.

  **Изменение:** Одна настроенная локальная учётная запись, серверная сессия и общий data-route guard; без IdP/RBAC. Cookie HttpOnly/SameSite, CSRF для мутаций, ограниченный Origin. UI login/logout и одинаковое поведение fetch/source/page (cookie применима к img/download). Credentials из env/file, не bundle. Только один local principal до добавления owner scope в C10/C11; multi-user режим пока отключён.

  **Файлы:** `phystech-trace/gateway/main.py`; `phystech-trace/gateway/requirements.txt`; `phystech-trace/frontend/src/api.ts`; `phystech-trace/frontend/src/App.vue`; `phystech-trace/tests/e2e/local_auth.py (новый)`.

  **Миграции:** для single local principal нет; owner_id добавляется C10.

  **Проверка:** Анонимные list/result/download/page/review/process отклоняются; login/logout и source image работают; cross-origin state mutation блокируется; cookie не доступна JS.

  **Готово, когда:** Нет открытого Gateway data route и обхода через Parser. Полная многопользовательская эксплуатация до C11 не заявляется.

  **Логи:** Session event/subject ID и action outcome, без password/cookie/bearer. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C04c — fix(extraction): enforce trusted external processing policy**

  Зависимости: C04a, C04b. Замечания: 5, 8 — минимальная защита.

  **Изменение:** Service auth и private data ports Extraction/Linking; перед каждым LLM вызовом читать действующую project policy из доверенного серверного источника. Тело запроса не расширяет согласие. До project-scoped storage C11 закрыть наружу глобальные history/latest/list и межпроектный cache reuse; запросы неопределённого scope отклонять. Для модельной разработки использовать frozen синтетические snapshots, не mutable проекты.

  **Файлы:** `phystech-trace/services/structured-extraction/runtime/server.mjs`; `phystech-trace/services/document-linking/server/app.ts`; `phystech-trace/gateway/main.py`; `phystech-trace/docker-compose.yml`; `phystech-trace/tests/e2e/service_policy.py (новый)`.

  **Доверенный per-send context:** Gateway/worker создают context из аутентифицированного project/run, не из одного allow_external_llm body. Resolver читает актуальную policy и scope перед каждым provider send, в том числе transport retry и repair. Пробросить beforeSend hook через matcher/worker и Extraction caller в transport; runtime integration path без доверенного hook/context fail-closed. Для baseline C05 заранее регистрируется отдельный synthetic project/consent и membership frozen fixtures; harness использует тот же server-side resolver, а не свободный JSON флаг. Прямой benchmark вне такого scope отклоняется.

  **Дополнительные файлы:** `phystech-trace/services/document-linking/src/linking/polza-client.ts`; `phystech-trace/services/document-linking/src/linking/llm-matcher.ts`; `phystech-trace/services/document-linking/server/worker.ts`; `phystech-trace/services/document-linking/server/project-policy.ts (новый)`; `phystech-trace/services/structured-extraction/lib/extraction/polza-ai.mjs`; `phystech-trace/services/structured-extraction/runtime/project-policy.mjs (новый)`. Cloudflare-compatible library не импортирует PostgreSQL resolver напрямую: его передаёт доверенный runtime caller.

  **Миграции:** нет на раннем периметре; доверенная policy уже есть в trace_projects. Scope storage меняется C10/C11..

  **Проверка:** Confidential→synthetic spoof, отсутствующий service token, чужой/несуществующий project, отзыв согласия перед send. В том числе отозвать согласие между первым send и retry/следующим чанком. Проверить ноль mock egress и отсутствие общей истории.

  **Готово, когда:** Нельзя получить данные внутренних сервисов или разрешить внешнюю передачу клиентским флагом. Завершённая изоляция storage остаётся C11 и обязательна при приёмке.

  **Логи:** Project/run IDs, policy decision/revision и safe reason code, без credentials/source text. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C05 — test(evaluation): freeze MVP gold and baseline**

  Зависимости: C02, C03, C03b, C04a–c; Q0.1 labels, Q0.2 параметры, Q0.5 разрешение запуска. Замечания: 2, 33, 34.

  **Исполняющий runner:** `phystech-trace/services/document-linking/scripts/run-mvp-baseline.ts (новый)`; `tests/mvp-baseline.test.ts (новый в document-linking)`. CLI `npx tsx scripts/run-mvp-baseline.ts --protocol evaluation/mvp-v1/protocol.json --phase baseline --base-url http://localhost:8084` регистрирует разрешённый synthetic scope и exact fixture membership, исполняет protocol matrix без изменения моделей, вызывает scorer C03 и Extraction scorer C03b, сохраняет raw predictions только в разрешённом защищённом каталоге и безопасный агрегированный report. Protocol явно задаёт paths существующих gold/snapshots и метаданные согласованного execution; restart/cached replay не увеличивает repeat count. Unit runner tests проверяют enumeration6×5, fail retention, missing permission/context rejection и limits без LLM.

  **Extraction gold:** `phystech-trace/services/structured-extraction/evaluation/mvp-v1/extraction-gold.json (новый, вручную проверенный по schema C03b)`; для каждого формата expected critical/noncritical fields, rows и provenance.

  **Изменение:** Человек завершает небольшой эталон Q1. После утверждения чисел заморозить hashes/config/policy, выполнить baseline 6×5 и extraction slice; сохранить per-run отчёт C03, все failures, budget usage/unknown. Private/неразрешённые документы и raw responses не коммитить. Зафиксировать source paths approved fixtures, а не backend/uploads.

  **Файлы:** `phystech-trace/services/document-linking/evaluation/mvp-v1/manifest.json (новый)`; `phystech-trace/services/document-linking/evaluation/mvp-v1/gold.json (новый, заполняет человек)`; `phystech-trace/services/document-linking/evaluation/mvp-v1/protocol.json (новый)`; `phystech-trace/services/document-linking/reports/mvp-baseline-v1.md (новый)`.

  **Миграции:** нет.

  **Проверка:** Повторная проверка hashes/gold completeness, scorer results и отрицательных fixtures. До live — отдельное разрешение на реальные вызовы/exposure; мок не выдавать за baseline реальной модели.

  **Готово, когда:** Есть реально измеренный baseline и подписанный человеком gold/quality policy. Неуспешный baseline допустим как исходная точка; отсутствующий baseline — стоп перед C06–C09.

  **Логи:** Protocol revision, source hashes, model configuration и per-run outcomes/usage; секретов/документов в отчёте нет. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

### Раннее исправление моделей

- [ ] **C06 — feat(linking): plan bounded tasks with complete source coverage**

  Зависимости: C05. Замечания: 1, 26.

  **Изменение:** Детерминированно планировать bounded tasks на immutable documents, учитывать prompt/schema/output reserve. Полное покрытие docs/rows/reference IDs, split больших элементов, task/input hash для checkpoint. Кандидаты не ограничиваются равенством сумм/номеров. Работа на сохранённом worker payload/frozen fixtures не зависит от полной новой Gateway schema.

  **Файлы:** `phystech-trace/services/document-linking/src/linking/llm-matcher.ts`; `phystech-trace/services/document-linking/src/linking/types.ts`; `phystech-trace/services/document-linking/src/linking/evidence-registry.ts`; `phystech-trace/services/document-linking/tests/linking.test.ts`.

  **Миграции:** нет; progress state version bump с явным запретом несовместимого resume.

  **Проверка:** Oversized row/string, межчанковые связи, порядок входов, last chunk, missing/duplicate reference, невписавшийся preflight. Проверить предел каждого mock request, не только исходного документа.

  **Готово, когда:** Нет запроса сверх согласованного per-call лимита, expected элементы не исчезают; checkpoint возобновляется только для совпавшего input/config hash.

  **Логи:** Task/hash/counts/token estimates и excluded/failed reasons; не логировать факты/значения. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C07 — fix(linking): merge bounded results without full-set LLM reduce**

  Зависимости: C06. Замечания: 1, 26.

  **Изменение:** Убрать финальный запрос со всеми summaries/registry. Выполнять ограниченные cross-chunk проверки и deterministic merge точных утверждений с проверкой references; дубли/направления/противоречия сохранять корректно. Не вводить закрытый словарь relationship types. Отдельно processed-no-link, unprocessed, review/failed.

  **Файлы:** `phystech-trace/services/document-linking/src/linking/llm-matcher.ts`; `phystech-trace/services/document-linking/src/linking/link-resolver.ts`; `phystech-trace/services/document-linking/src/linking/evidence-validation.ts`; `phystech-trace/services/document-linking/tests/linking.test.ts`; `phystech-trace/services/document-linking/tests/evidence-validation.test.ts`.

  **Миграции:** нет.

  **Проверка:** Исходный полный комплект через mock boundary, связь между последними чанками разных документов, duplicate relation с разными row instances, conflict и полностью отрицательный набор. Контракт 1.2.0 валиден.

  **Готово, когда:** Полнота и evidence валидируются без огромного final context. До live-качества не заявлять успех семантики по одному mock.

  **Логи:** Merge input/task IDs, counts accepted/rejected/conflicting и coverage status. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C08 — fix(linking): recover malformed fragments with bounded retries**

  Зависимости: C06, C07. Замечания: 15, 1.

  **Изменение:** Разделить transport/JSON/schema/reference/semantic errors; retry только повреждённой части, максимум Q1 repair attempts в общих лимитах. При truncation уменьшать chunk, не придумывать хвост JSON; после budget/cancel не отправлять новые запросы. Валидные checkpoints сохранять.

  **Файлы:** `phystech-trace/services/document-linking/src/linking/polza-client.ts`; `phystech-trace/services/document-linking/src/linking/llm-matcher.ts`; `phystech-trace/services/document-linking/server/worker.ts`; `phystech-trace/services/document-linking/tests/polza-client.test.ts`; `phystech-trace/services/document-linking/tests/linking.test.ts`.

  **Миграции:** нет.

  **Проверка:** Truncated/malformed JSON, wrong ID/value, 429/5xx, 401/403, late response; восстановление последнего чанка не повторяет всё. Schema/evidence не ослаблены.

  **Готово, когда:** Recovery либо даёт строго проверенный fragment, либо явный partial/failed; неполный результат не completed.

  **Логи:** Error category, task/attempt and remaining counters; raw provider text не публикуется. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C09 — fix(extraction): ground staged LLM mappings in exact parser values**

  Зависимости: C05; после C08 в основной очереди, можно независимую работу без нарушения baseline. Замечания: 3, 15.

  **Изменение:** Разделить классификацию, mapping заголовков и поля; передавать ограниченный набор реальных IDs. Диагностировать POLZA_UNGROUNDED_OUTPUT по точной причине. Модель возвращает смысл/ссылки, сервер берёт значения из Parser; большой table schema analysis не объявлять просмотром всех строк. Строгий llm-required тестовый режим запрещает засчитать fallback.

  **Файлы:** `phystech-trace/services/structured-extraction/lib/extraction/polza-ai.mjs`; `phystech-trace/services/structured-extraction/lib/extraction/structured-extraction.mjs`; `phystech-trace/services/structured-extraction/tests/polza.test.mjs`; `phystech-trace/services/structured-extraction/tests/extraction.test.mjs`; `phystech-trace/services/structured-extraction/runtime/server.mjs`.

  **Миграции:** нет.

  **Проверка:** PDF/XLSX/DOCX/сложные tables, wrong header vs cell ID, missing context source, повторные заголовки, merged/formula, forged values. Проверить успешную LLM-ветку отдельно от rules_only.

  **Готово, когда:** Grounding не ослаблен; обработка/отказы структурированы; успех на mocked correct references и соответствующий live gate в C21.

  **Логи:** Mode, source context hash, validation reason/counts и attempts; source text/credentials не логировать. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

### Согласованность данных и экспертная работа

- [ ] **C10 — feat(storage): migrate minimal run manifests and project scope**

  Зависимости: C04a–c; в основной очереди после C09. Замечания: 8, 10, 20.

  **Изменение:** Минимальный trace_schema_migrations ledger/lock и baseline check, отдельный от существующего Linking schema_migrations. В projects добавить owner_id/input_revision/active_run_id/current_run_id; создать trace_processing_runs с immutable input_snapshot/manifest_hash и status/cancel/counters; Extraction добавить project_id/project_document_id/upstream input hash. Существующие JSONB/files сохранить. Legacy не приписывать версии/владельца случайно; неоднозначные records закрыть.

  **Файлы:** `phystech-trace/migrations/001_trace_run_scope.sql (новый)`; `phystech-trace/migrations/002_extraction_scope.sql (новый)`; `phystech-trace/scripts/migrate.py (новый)`; `phystech-trace/gateway/main.py`; `phystech-trace/services/structured-extraction/runtime/server.mjs`; `phystech-trace/docker-compose.yml`; `phystech-trace/tests/contracts/test_database_migrations.py (новый)`.

  **Миграции:** 001: проекты/run snapshots/ledger; 002: nullable scope columns → проверенный backfill → scoped indexes/constraints. Не удалять старые payload в этом коммите, не ломать Linking migration ledger..

  **Проверка:** Новая БД, сохранённая 2e6da4b2, повтор/конкурентный migrator, failed backfill; bytes/payload hashes и evidence сохраняются. Run insert атомарен со snapshot.

  **Готово, когда:** Новая схема применяется явным шагом до startup и проверяется сервисами; нет отдельного object storage/полного artifact registry.

  **Логи:** Migration ID/checksum, counts backfilled/quarantined и schema compatibility, не payload. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C11 — fix(extraction): scope history cache and atomic versions**

  Зависимости: C10. Замечания: 8, 11, 5.

  **Изменение:** Включить project-scoped endpoints/cache/version: project_document instance + computation fingerprint. Counter/upsert и payload INSERT в одной транзакции; UNIQUE(instance, version) и fingerprint сохраняют идемпотентность. Обновить public Gateway result lookup и owner checks; ранние закрытые listing открывать только с доказанным scope.

  **Файлы:** `phystech-trace/gateway/main.py`; `phystech-trace/services/structured-extraction/runtime/server.mjs`; `phystech-trace/migrations/003_extraction_version_counter.sql (новый)`; `phystech-trace/tests/e2e/extraction_concurrency.py (новый)`; `phystech-trace/tests/e2e/project_isolation.py (новый)`.

  **Миграции:** 003: counter row/constraints, уникальность scoped idempotency. Точное старое UNIQUE заменить только после backfill и совместимости readers..

  **Проверка:** 20 конкурирующих одинаковых requests → один artifact; разных → уникальные versions; два проекта с одним Parser ID не видят чужую историю/согласие/cache.

  **Готово, когда:** Нет MAX+1 race failure при штатной конкуренции, нет межпроектного computed-result reuse и unscoped read.

  **Логи:** Scope IDs, version allocation/idempotency outcome и DB errors без payload. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C12 — fix(gateway): snapshot active inputs and invalidate stale results**

  Зависимости: C10, C11. Замечания: 6, 7, 10, 13 — упрощённо.

  **Изменение:** Под одной проектной транзакционной проверкой сериализовать upload/start и фиксировать manifest. Во время active run upload 409. process_project читает run snapshot, не mutable document_rows. Различить omitted patch и explicit NULL вместо COALESCE; invalidation снимает current, не историю. Один Gateway; conditional publication по active_run_id/revision; retry/resume только matching input/config.

  **Файлы:** `phystech-trace/gateway/main.py`; `phystech-trace/tests/e2e/project_revision.py (новый)`; `phystech-trace/tests/e2e/concurrent_start.py (новый)`; `phystech-trace/docker-compose.yml`.

  **Миграции:** использует C10; новой migration нет.

  **Проверка:** Upload/start barrier, два process/retry, новая Extraction после completed, late old completion, mismatched resume, snapshot после restart. Проверить no current stale и неизменные исторические данные.

  **Готово, когда:** В supported single-process профиле нет ложного completed старой revision; один logical run. Несколько replicas остаются запрещены.

  **Логи:** Run/revision transitions, invalidation reason, claim/current compare outcome, без source names. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C13 — fix(pipeline): gate parser quality and explicit coverage**

  Зависимости: C09, C12. Замечания: 9, 26.

  **Изменение:** Версионированное решение accepted/limited/review/blocked по реальным Parser status/quality/warnings/stale/confirmation. Проверять exact input manifest и coverage на выходе Linker. Не блокировать любое warning без классификации; не пропускать критичную неопределённость под видом ready.

  **Файлы:** `phystech-trace/gateway/main.py`; `phystech-trace/contracts/parser-to-extraction-v1.schema.json`; `phystech-trace/tests/contracts/test_contracts.py`; `phystech-trace/tests/e2e/parser_quality.py (новый)`.

  **Миграции:** нет, решение хранится в существующем run snapshot/status metadata.

  **Проверка:** Ready+partial/stale/unknown, нераспознанная сумма, некритичный warning, пропавший документ/row, complete negative graph. Contract extensions совместимы.

  **Готово, когда:** Ready не равен качеству; current completion и ограниченность отражают policy, необработанные элементы перечислены.

  **Логи:** Policy version/admission outcome/reason и coverage counts. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C14 — feat(pipeline): enforce persistent limits and cancellation**

  Зависимости: C08, C09, C12. Замечания: 16, 14.

  **Изменение:** Общие сохраняемые calls/input/output/deadline counters и cancel flag на run. Проверять разрешение/остаток до каждого provider request, включать repairs обоих модулей. Late response не возобновляет отменённый run; resource limits не притворяются денежным ledger.

  **Файлы:** `phystech-trace/gateway/main.py`; `phystech-trace/services/document-linking/server/worker.ts`; `phystech-trace/services/structured-extraction/runtime/server.mjs`; `phystech-trace/frontend/src/api.ts`; `phystech-trace/tests/e2e/limits_cancel.py (новый)`.

  **Миграции:** использует run fields C10; нет нового финансового ledger.

  **Проверка:** Граница каждого Q1 limit, два этапа, retry/restart, неизвестный usage, cancel до/во время request и перед publication.

  **Готово, когда:** Новые запросы после stop/лимита не отправляются; counter не сбрасывается при recovery. Возможный уже понесённый расход отмечен unknown.

  **Логи:** Counters/residual limits/cancel state и provider event status без текста запроса. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C15 — fix(ui): resolve evidence paths against exact source snapshots**

  Зависимости: C12, C13. Замечания: 28, 27.

  **Изменение:** Строить path по source table/row indices и версии, не ID/позиции отсортированного UI. Проверять resolve/raw value в настоящем JSON; не подменять похожим полем. Сохранить allowed unknown fields/coordinates/merged metadata round-trip.

  **Файлы:** `phystech-trace/frontend/src/App.vue`; `phystech-trace/frontend/src/types.ts`; `phystech-trace/frontend/src/components/EvidencePanel.vue`; `phystech-trace/tests/e2e/evidence_paths.py (новый)`.

  **Миграции:** нет.

  **Проверка:** Несколько таблиц/произвольные row IDs, sort/filter, ключ с точкой, zero/null, historical result. Каждый click даёт точный source value.

  **Готово, когда:** Evidence всех показанных полей и связей разрешимо до верного snapshot. XLSX grid не добавляется.

  **Логи:** Safe locator resolution error с run/doc IDs, без значений. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

### Эксплуатация и приёмка

- [ ] **C16 — fix(review): separate machine acceptance from human decisions**

  Зависимости: C04b, C12, C15. Замечания: 32, 29 — минимум.

  **Изменение:** Все machine links с not_reviewed доступны reviewer, включая confirmed. Хранить actor/run/link/evidence revision и историю решения; conflicting update отклоняется. Дать авторизованное скачивание полного Parser JSON, preview32 явно краткий. Полноценные viewer/search отложены. Передавать actor из доверенного Gateway; в Linking сохранить неизменяемый machine_result_json при saveRun и записывать actor/decision/fingerprint в append-only review audit внутри существующей транзакции updateDecision. Неизвестный исходный machine result старых уже reviewed записей пометить legacy_unknown, не восстанавливать догадкой.

  **Файлы:** `phystech-trace/frontend/src/App.vue`; `phystech-trace/frontend/src/api.ts`; `phystech-trace/gateway/main.py`; `phystech-trace/tests/e2e/review_decisions.py`; `phystech-trace/tests/e2e/full_parser_json.py (новый)`; `phystech-trace/services/document-linking/server/app.ts`; `phystech-trace/services/document-linking/server/storage.ts`; `phystech-trace/services/document-linking/migrations/postgres/0002_review_audit.sql (новый)`.

  **Миграции:** Linking 0002_review_audit.sql: machine_result_json и таблица review_decisions(run_id, link_id, actor_id, expected_fingerprint, decision, created_at); минимальный backfill с legacy_unknown, без отдельного Gateway журнала и распределённого outbox..

  **Проверка:** Все допустимые status×verification комбинации, два конфликтующих reviewers/updates, старый run, direct PATCH без auth; последний из33+parts есть в полном JSON.

  **Готово, когда:** Машинное подтверждение не выглядит человеческим; полный сохранённый JSON доступен без потери provenance.

  **Логи:** Decision transition/actor/run/revision и denied conflicts; reason text выводить только в защищённом аудите. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C17 — fix(health): expose real readiness and basic queue status**

  Зависимости: C04a–c, C12. Замечания: 17, 18 минимум, 31.

  **Изменение:** /live и /ready с 503 при обязательной dependency failure, safe status/capabilities snapshot для UI. Basic queue connectivity вместо PID-only; не выдавать Redis PING за stuck-consumer detection. Freshness/unknown/blocked различимы; заменить статическую готовность.

  **Файлы:** `phystech-trace/gateway/main.py`; `phystech-trace/gateway/Dockerfile`; `phystech-trace/docker-compose.yml`; `phystech-trace/frontend/src/App.vue`; `phystech-trace/frontend/src/api.ts`; `phystech-trace/tests/e2e/service_readiness.py (новый)`.

  **Миграции:** нет.

  **Проверка:** БД/upstream/Redis down и recovery, upstream200+degraded, CLIENT not ready, UI out-of-order/stale snapshot; живой процесс не бесконечно рестартует из-за чужого outage.

  **Готово, когда:** Container probe и UI используют фактический статус; расширенная telemetry worker не prerequisite.

  **Логи:** Probe category/status/duration и stale age, без connection strings. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C18 — test(recovery): cover basic restart and persistence cases**

  Зависимости: C11–C14, C17. Замечания: 14 — базово.

  **Изменение:** Синтетические persisted stages: restart Gateway в OCR/Extraction, restart worker, краткая недоступность PostgreSQL, partial model response. Использовать mock transport и реальные БД/HTTP, фиксировать logical identity до side effect.

  **Файлы:** `phystech-trace/tests/e2e/recovery_basic.py (новый)`; `phystech-trace/tests/e2e/README.md`; `phystech-trace/services/document-linking/tests/infrastructure.integration.test.ts`.

  **Миграции:** нет.

  **Проверка:** Сценарии запускаются на сохранённых volumes с before/after IDs/counters/hashes; fail если eternal running, duplicate logical result, lost document или false completed.

  **Готово, когда:** Базовый recovery повторяем без полной chaos framework. Unknown provider outcome не выдаётся за exactly-once или бесплатный retry.

  **Логи:** Fault timeline, run/stage IDs, before/after counters и reconciliation outcome. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C19 — fix(docs): use correct parser origin and basic API smoke**

  Зависимости: C04a, C17. Замечания: 23, 25 минимум.

  **Изменение:** Относительный Parser servers.url/proxy prefix. После скрытия портов согласовать UI docs links: authenticated Gateway docs proxy либо явный diagnostic profile без раскрытия service token. Не сохранять якобы работающие ссылки на закрытый8081. Проверить основные HTTP success/errors, auth и binary content по спецификациям.

  **Файлы:** `phystech-trace/services/document-parser/openapi.json`; `phystech-trace/services/structured-extraction/runtime/openapi.json`; `phystech-trace/services/document-linking/openapi.yaml`; `phystech-trace/tests/e2e/openapi_smoke.py (новый)`; `phystech-trace/frontend/src/api.ts`; `phystech-trace/gateway/main.py`.

  **Миграции:** нет.

  **Проверка:** Integration/private Parser + standalone diagnostic origin, source/page bytes, 401/403/404/422, ready503; реальный Swagger request URL. Linking8083 не возвращать к старому ошибочному порту.

  **Готово, когда:** Документация доступна выбранным разрешённым способом, Try it out не обходит ACL; basic API smoke реально исполняется.

  **Логи:** Operation/status/schema mismatches без raw documents/tokens. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C20 — test(repository): audit runtime documents and prevent new uploads**

  Зависимости: аудит начинается сразу; исправления после подтверждённой классификации. Замечания: 22.

  **Изменение:** Закрытый реестр path/blob hash/provenance/permission/owner; публично только агрегаты. Разрешённые fixtures отделить от runtime uploads; непредназначенные файлы убрать из текущего индекса по итогам проверки, добавить CI denylist. Это не автоматическое разрешение history rewrite/force push.

  **Файлы:** `docs/document-publication-audit.md (новый, только безопасные агрегаты)`; `backend/uploads/ (только после проверки разрешений)`; `.gitignore`; `.github/workflows/integration.yml`.

  **Миграции:** нет.

  **Проверка:** Проверить tracked inventory и allowlist, тесты не зависят от private uploads, CI блокирует новое runtime содержимое.

  **Готово, когда:** Права/действия по каждому файлу определены; если требуется очистка истории, отдельное согласованное действие остаётся открытым до выполнения.

  **Логи:** Counts/classification status; не выводить содержимое, персональные данные или секреты из корпуса. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

- [ ] **C21 — test(e2e): enforce MVP quality and representative mock pipeline**

  Зависимости: C06–C19, C20 по результатам аудита; C01 для CI. Замечания: 1–3, 26–28, 32–35.

  **Изменение:** Mock заменяет только provider boundary в обоих LLM этапах; настоящие Parser/Extraction/Linking/Gateway/БД остаются. Запустить полный корпус, foreign scope, no-egress confidential block, stale/results/source/row assertions. После отдельного согласования live повторить тот же frozen протокол и заполнить candidate report через исправленный scorer; mock не доказывает точность модели.

  **Файлы:** `phystech-trace/tests/e2e/run_e2e.py`; `phystech-trace/tests/e2e/verify_saved_project.py`; `phystech-trace/tests/e2e/README.md`; `phystech-trace/tests/e2e/mock_provider.py (новый)`; `phystech-trace/services/document-linking/evaluation/mvp-v1/protocol.json (новый в C05)`; `.github/workflows/integration.yml`.

  **Миграции:** нет.

  **Проверка:** Все утверждённые Q1 gates по каждому повтору, базовые recovery/coverage/path/API проверки. ВалидныйJSON с wrong evidence обязательно отклоняется. Full-set live действительно завершён, llm-required не fallback.

  **Готово, когда:** Root CI реально проходит unit/contract/build/mock E2E; live report сравнен с baseline на frozen gold и утверждённых лимитах. Для failing gate MVP не объявляется готовым.

  **Логи:** Safe per-scenario/per-repeat gate outcomes и usage/unknown, без приватных artifacts. INFO — major state transitions; WARN — rejection/retry; ERROR — failed. DEBUG только безопасные IDs/counters, без source contents.

## Контрольные команды будущего исполнения

Команды ниже описаны для будущего разработчика; **сейчас не запускались и не разрешены ответом об утверждении Q1**. Для существующих npm scripts рабочая папка указана явно; новые CLI-флаги/tests должны быть добавлены соответствующим task до первого запуска.

| Checkpoint | Рабочая папка | Команда/вход | Статус интерфейса |
| --- | --- | --- | --- |
| Backend | Корень | python -m unittest discover -s backend/tests -v | Существующий entrypoint; тесты auth добавляет C04a |
| Contracts | Корень | python -m unittest discover -s phystech-trace/tests/contracts -v | Существующий entrypoint |
| Annotation | phystech-trace/services/document-linking | npm run eval:prepare-annotations -- --mode single --out evaluation/mvp-v1/packets | Новые флаги C02; не считать уже работающими |
| Gold compile | phystech-trace/services/document-linking | npm run eval:compile-annotations -- --mode single --packets evaluation/mvp-v1/packets --out evaluation/mvp-v1/gold.json | Новые флаги C02; gold заполняет человек |
| Scorer unit | phystech-trace/services/document-linking | npx tsx --test tests/evaluation-metrics.test.ts | Новый test C03 |
| Score repeats | phystech-trace/services/document-linking | npm run eval:links -- evaluation/mvp-v1/gold.json --out reports/mvp-baseline-v1.json | Существующая форма CLI; per-repeat исправляет C03, prediction paths заполняет C05 |
| Linking regression | phystech-trace/services/document-linking | npm test; npm run build | Существующие scripts, последовательные команды |
| Extraction regression | phystech-trace/services/structured-extraction | npm test | Существующий unit entrypoint, не Cloudflare test:api |
| Migrations | Корень/среда с PostgreSQL | python phystech-trace/scripts/migrate.py --database-url-env DATABASE_URL | Новый CLI C10, секрет не в argv |
| Vue | phystech-trace/frontend | npm run typecheck; npm run build | Существующие scripts |
| Mock E2E | Корень | python phystech-trace/tests/e2e/run_e2e.py --base-url http://localhost:8084 --llm-mode mock --protocol phystech-trace/services/document-linking/evaluation/mvp-v1/protocol.json | Новые flags C21; реальные сервисы/БД остаются |
| Live E2E | Корень | Тот же runner с --llm-mode live и frozen protocol, после отдельного разрешения | Новые flags C21; credentials читаются из среды, не выводятся |

Для каждого нового HTTP test file из Tasks добавить main/argparse с --base-url и nonzero exit при failure. Recovery runner дополнительно получает --compose-project для изолированного стенда; он не должен рестартовать чужой Compose project. Команды с точкой с запятой в таблице — список последовательных проверок, а не требование объединять shell-запуски.

## Условные коммиты и следующий backlog

- **P01 перед публикацией, №19:** `phystech-trace/docker-compose.production.yml` (новый), существующие config/config-check/README — уникальные secrets, production defaults validation, closed ports, auth; тест negative startup. Не выполнять deployment автоматически.
- **O01 только для offline demo, №24:** локальные swagger-ui-dist assets в Parser/Extraction/Linking images и соответствующих server HTML; тест запрещает внешние браузерные запросы. Скрытие Parser порта/наличие Gateway docs proxy учитывать по C19.
- **L01 перед confidential-пилотом, №12:** отдельный provider adapter и реальный no-egress confidential E2E/quality report; до этого blocked, без внешнего fallback.
- **W01 перед Gateway replicas, №13:** распределённое владение/lease/fencing отдельно, повторный recovery audit. Active_run_id в одном процессе не выдаётся за готовность к multi-replica.
- **После измерений №21:** стратегия хранения/retention/GC; сейчас только замер размеров.
- **После backend stability №18/29/30:** heartbeat/stuck worker detection, полноценный Parser search/virtualization и XLSX grid.
- **Предметный этап №36:** после C21 отдельный дизайн ОСВ, ожидаемых значений, суммирования, периодов и сверки. Финансовые формулы/допуски не подставляются из Q1: это технические quality gates, не бухгалтерская методика.

## Покрытие 35 замечаний

| Замечания | Задачи или условная работа |
| --- | --- |
| 01, 15, 26 | C06–C08, C13, C21 |
| 02, 33 | C02, C03, C03b, C05, Q0 и Q1 |
| 03 | C03b, C05 baseline, C09, C21 |
| 04, 05, 08 | C04a–c, C10, C11; Parser выделен явно |
| 06, 07, 10, 11, 13 | C10–C12; W01 только до replicas |
| 09 | C13 |
| 12 | L01 позже; safe blocked тест C04c/C21 сейчас |
| 14, 16 | C14, C18 |
| 17, 18, 31 | C17; расширенный №18 позже |
| 19 | P01 до публикации |
| 20 | C10/C11/C16 перед соответствующими schema changes |
| 21 | Измерения сейчас, retention позже |
| 22 | C20 |
| 23, 25 | C19, basic smoke |
| 24 | O01 при offline demo |
| 27, 28 | C01, C10–C15, C21 |
| 29, 30, 32 | C15/C16: locator/review/full JSON; advanced viewers позже |
| 34, 35 | C01, C18, C21 |

## Условия завершения и отката

Только measured results при утверждённых порогах дают основание приёмки. На каждом commit сначала воспроизведение регрессии, затем изменение и тот же targeted test; полный suite — на соответствующем checkpoint, не многократно без причины. При провале не ослаблять evidence/gold и не удалять сложный fixture.

Runtime changes держать совместимыми с pinned 1.2.0. Миграции additive/backfilled: перед destructive alter — backup/restore и отдельная ревизия плана. Историю Git не переписывать в C20 без отдельного решения. Код и prompt baseline сохраняются как immutable версия; candidate вправе содержать именно сравниваемые изменения алгоритма/prompt, с отдельными commit/prompt hashes. Корпус, единицы оценки, модель и resource/quality policy остаются одинаковыми, все намеренные различия раскрываются. При изменении corpus/policy/model исходное сравнение архивируется, запускается новая версия протокола, не переписывается старый baseline.

Документационный checkpoint каждого изменяющего контракты коммита: README, docs/data-flow.md, docs/contracts.md и OpenAPI отражают реальное поведение/auth/режим запуска. Не заявлять тест или deployment исполненным без результата.

## Review status

План ещё не исполнялся. Q0.2 закрыт только в части предварительного утверждения Q1. Ручной gold Q0.1, measured baseline Q0.3 и отдельное разрешение на тесты Q0.5 остаются будущими gates.

Approved policy Q1 SHA256: 10b530c694ab0f916e3902d64b40d8b0073c11c1d7f8dd1ec6212208382a8864


Проверка плана: read-only review закрыл конкретность per-send policy и Extraction baseline; исправлены таблицы.24 открытые implementation-задачи совпадают с24 commit checkpoints. Локальные ссылки, Q1 policy hash и source Active Summary hash проверены. Это не исполнение задач и не запуск application tests.
