# 18. Проверка работоспособности Linking worker

[Общий индекс](00-index.md) · 🟠 Серьёзно

Дата исследования: 13.11.2026. Срез: `feat/phystech-trace-integration`, `2e6da4b2b3b57b5c4e9137d8657770beba65ffdf`.
Статус: предложение к реализации; исправления и повторные live/Docker-прогоны в рамках исследования не выполнялись.

## Объём следующего стабильного MVP

**Вердикт пользователя: Позже; простая проверка сейчас.**

Для локального MVP достаточно проверки доступности очереди и основных ошибок worker; расширенный heartbeat/stuck detection отложить.

Объём ниже уточнён по пользовательской оценке всех 35 планов. Расширенные решения не являются обязательствами MVP; отложенное замечание не считается устранённым. Исследование остаётся без реализации.

## Что подтверждено

Compose healthcheck проверяет только наличие PID 1.

- [phystech-trace/docker-compose.yml](../../phystech-trace/docker-compose.yml) — linking-worker healthcheck: process.kill(1,0).
- [phystech-trace/services/document-linking/server/worker.ts](../../phystech-trace/services/document-linking/server/worker.ts) — BullMQ worker, heartbeatJob, worker error events.
- [phystech-trace/services/document-linking/server/worker-main.ts](../../phystech-trace/services/document-linking/server/worker-main.ts) — Точка запуска отдельного worker процесса.

## Причина и границы вывода

Живой PID не означает подключение Redis/БД, активный consumer или возможность продолжить checkpoint.

## Рекомендуемое решение

В локальном MVP заменить PID-only представление на простую проверку доступа к Redis/очереди и обработку worker startup/error state. Такой probe описывать как доступность очереди, не как доказанную способность завершить произвольное задание. Работоспособность consumer проверяет базовый mock E2E.

## Последовательность будущего изменения

1. Проверять соединение с очередью с timeout и выводить безопасную причину ошибки worker.
2. Отделить queue available от job success. Не вызывать реальную LLM в регулярном probe.
3. Сохранить существующие механизмы BullMQ retries и recovery; расширенную телеметрию пока не добавлять.

## Проверка исправления

- Redis недоступен — probe не зелёный; после восстановления состояние обновляется.
- Mock E2E подтверждает фактическое получение и завершение задания worker.

## Критерий приёмки MVP

Для MVP доступность очереди проверяется, ограничения probe явно описаны, обработка подтверждена E2E. Полное исходное замечание о stuck consumer остаётся отложенным.

## Что отложено

Boot-aware heartbeat, active progress deadlines, stuck consumer detection и отдельный synthetic canary — перед многопроцессной эксплуатацией.

Исходная расширенная проработка ниже сохранена как справочный вариант; она не расширяет текущий scope. При расхождении объёма приоритет имеют разделы MVP выше.

## Расширенный вариант для следующих этапов

Worker публикует heartbeat с boot_id, worker_id, last successful queue interaction, DB connectivity, readiness, active job и last progress timestamp. Probe проверяет свежесть собственного экземпляра и доступность необходимых хранилищ.

## Расширенный вариант: возможные шаги

1. Начальное состояние starting; ready только после соединения и регистрации consumer. Отличать намеренный pause/drain от ошибки.
2. Не требовать наличия успешно выполненного job при пустой очереди. Для долгого LLM-вызова heartbeat остаётся живым, а progress deadline равен обоснованному timeout.
3. При event-loop hang heartbeat перестаёт обновляться; устаревший heartbeat предыдущего boot не засчитывается.
4. Readiness может включать лёгкий canary через mock processor в отдельной диагностике; реальную LLM в регулярный healthcheck не вызывать.

## Расширенный вариант: будущие проверки

- Redis down, DB down, consumer закрыт при живом процессе, заблокированный event loop, пустая очередь.
- Длинный допустимый job остаётся healthy; превышенный processing deadline отражается как stuck и допускает recovery.

## Критерий полного закрытия исходного замечания

Probe различает живой, но неспособный работать worker, idle и busy; health state подтверждён сценарием реальной очереди.

## Зависимости и ограничения

Связанные замечания: [№13](13-gateway-distributed-execution.md), [№14](14-recovery-fault-injection.md), [№17](17-gateway-liveness-readiness.md), [№35](35-integration-ci.md). Ссылки означают совместное проектирование или общую проверку, а не обязательный последовательный порядок; порядок задан в индексе.

Один Redis PING не доказывает, что consumer получает задания; нужен собственный worker state и проверка свежести.

