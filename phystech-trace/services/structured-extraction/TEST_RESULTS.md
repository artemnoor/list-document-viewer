# Structured Extraction — локальные результаты проверок

Дата: 2026-11-12 20:52 MSK

Коммит кода под проверкой: `99b5634f0f0c63d4dde6345b248c41a5ca3a9b49`

Среда: Windows, PowerShell, локальный Worker и локальная D1.

## Результаты

| Проверка | Результат | Примечания |
| --- | --- | --- |
| `npm test` | PASS — 40/40 | Parser, provenance, extraction, Compare, confidence, Polza adapter, security, D1 seed. |
| `npm run test:api` | PASS | Локальная D1, авторизация, импорт, версии входа, история и повторное чтение. |
| `npm run test:polza` | PASS | Реальный `GET /models`, Compare-запрос к `deepseek/deepseek-v4-flash`, локальная валидация и сохранение/повторное чтение результата из D1. Тест завершился без `SKIP`. |
| `npm run build` | PASS | Production build завершён. |
| `npm run db:migrate:local` | PASS | Wrangler использовал только local resource; миграций к применению нет. |
| `git diff --check` | PASS | Ошибок whitespace нет. |

## Ограничения и предупреждения

- Реальный LLM smoke проверяет один демонстрационный документ КФЗ; это не оценка точности модели по всем типам документов.
- `npm test` использует синтетические fixtures и oracle assertions. Их результаты не являются независимой оценкой качества на реальном корпусе.
- Build вывел предупреждения Node.js о `punycode` и experimental `glob`, предупреждение о времени работы Vite plugins и замечание Vinext о статической классификации динамических API-маршрутов. Сборка завершилась успешно.

Ключ Polza не включён в этот отчёт. Проверки выполнялись на локальной D1; production D1 и deployment не использовались.
