# 33. Небольшой вручную проверенный benchmark MVP

[Общий индекс](00-index.md) · 🟠 Серьёзно · [Q1](38-quality-gates.md) · [Единый план](../../.ai-factory/PLAN.md)

Срез исходного кода: 2e6da4b2. Статус: план, без реализации и запусков тестов.
Уточнение пользователя: один человек проверяет небольшой эталон сейчас; второй разметчик и арбитраж — при расширении. Это supersedes прежнее требование двух экспертов для ближайшего MVP.

## Объём следующего стабильного MVP

**Сейчас:** вручную проверенный frozen gold, корректный scorer и повторные измерения до оптимизации. Один разметчик не должен выводить labels из predictions оцениваемой модели. Результат честно называется single-reviewer MVP benchmark; независимость от predictions не равна независимой двухэкспертной оценке.

Q1 предварительно утверждён пользователем. Назначение проверяющего, содержание labels и фактические baseline-метрики пока не выполнены; тесты запускаются после отдельного согласования.

## Что подтверждено

- [evaluation/README.md](../../phystech-trace/services/document-linking/evaluation/README.md) содержит scorer/packets, но не завершённый независимый gold.
- [compile-expert-annotations.ts](../../phystech-trace/services/document-linking/scripts/compile-expert-annotations.ts) сейчас требует три разные identities для двух reviewers и арбитра. В [annotations.schema.json](../../phystech-trace/services/document-linking/evaluation/annotations.schema.json) reviewer_ids допускает одну запись. Нужен явный single-reviewer mode, а не формальные выдуманные identities.
- [evaluate-links.ts](../../phystech-trace/services/document-linking/scripts/evaluate-links.ts) читает все repeats, но качество считает только для results[0]. В evidence-счётчике использует references всех gold relations сценария вместо соответствующей связи; row handling и validation также требуют уточнения.
- Точные точки изменения/проверки записаны в C02/C03 единого плана. Эти дефекты scorer найдены статически, новые regression tests здесь не выполнялись.

## Причина и границы вывода

Неправильный измеритель способен скрыть ухудшение повторов. Большой экспертный процесс задерживает первый локальный MVP. Уменьшение процесса разметки допустимо при сохранении точных источников, покрытия и честном описании ограничений.

## Рекомендуемое решение

Один человек вручную проверяет 6 небольших комплектов Q1: положительные, отрицательные, неоднозначные и межчанковые случаи, включая исходный полный набор. До predictions фиксируются направления, строки, evidence и critical fields. Источники/hash/проверяющий/version записываются; pending не считается negative. Заморозить dev/holdout разделение и protocol.

## Последовательность будущего изменения

1. C02: single-reviewer annotation compiler с теми же проверками hashes/path/value/coverage, без обязательного арбитра. Полный экспертный режим остаётся отдельным.
2. C03: scorer валидирует вход/выход и hashes, считает каждое повторение, correct relation-level paired evidence, doc/row units, negatives/ambiguity/N/A; сравнивается с ручными арифметическими fixtures.
3. Q0/C05: человек заполняет gold, утверждённый Q1 фиксируется hash, запускаются baseline 6×5 и extraction slice после отдельного согласования тестов.
4. Только затем C06–C09: изменение Linking/Extraction/repair. Тот же corpus/config/protocol после изменений; пороги не подгонять под результат.

## Проверка исправления

- Reviewer mode, pending/неполная пара, неправильный hash/path/value, вымышленный reviewer — проверки compiler.
- Поздний repeat хуже первого, wrong/paired evidence, пропуск, direction, несколько row instances, ambiguity и malformed JSON — ручные ожидаемые counts scorer.
- Per-repeat gates и численные лимиты — [утверждённый Q1](38-quality-gates.md). Baseline сейчас «не измерено»; compact smoke не заменяет его.

## Критерий приёмки MVP

Есть небольшой действительно проверенный человеком gold и измеренные результаты всех повторов через корректный scorer; Q1 проходит или честно провален. Два эксперта не prerequisite. Без измерений нельзя утверждать, что точность выросла.

## После расширения

Вторая независимая разметка, арбитраж, расширенный корпус, межэкспертное согласие и интервалы неопределённости. Первоначальные 10 scenario descriptions остаются candidate coverage plan, не готовым gold. На малом MVP эталоне нельзя заявлять промышленную точность КФЗ.

## Зависимости и ограничения

Связанные замечания: №1–3, 26, 34, 35. Единый порядок задаёт [PLAN.md](../../.ai-factory/PLAN.md). Человек и допустимый live exposure остаются внешними зависимостями; нельзя заменить их самоназначенными модельными labels.
