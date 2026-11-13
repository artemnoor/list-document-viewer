# Классификация несоответствий

Категория не выводится только из арифметики. Установленная причина (`established=true`) сопровождается ссылками на данные; неподтверждённое объяснение маркируется как `hypothesis=true`.

| Category | Когда выставляется |
| --- | --- |
| `amount_difference` | Decimal разница доказана на полной и подтверждённой базе |
| `wrong_period` | Actual и expected period явно заданы и различаются |
| `duplicate_operation` | Reconciliation указал confirmed duplicate; минимум два разрешённых source IDs используют один и тот же operation ID |
| `missing_supporting_document` | Диагностика подтверждена, document ID указан в `excluded_sources`, а подтверждающие ссылки разрешаются |
| `incorrect_document_link` | Link отвергнут человеком (установленная причина) либо связь ещё не подтверждена (гипотеза/review) |
| `quantity_or_indicator_difference` | Отличается поддерживаемое числовое значение, не являющееся money |
| `incompatible_unit` | Currency или unit явно несовместимы; сравнение не выполняется |
| `rounding_problem` | Явное rounding rule объясняет raw difference, либо неизвестное правило сохранено как гипотеза |
| `conflicting_primary_documents` | Reconciliation сообщает конфликт двух или более разрешённых source IDs с разными значениями |
| `unsubstantiated_cause` | Разница установлена, но причина ею не подтверждается |
| `economic_meaning_mismatch` | Тип, plan/actual basis или VAT basis не совпадает |

Несколько категорий могут находиться на одном показателе. Например, подтверждённый периодный конфликт и отсутствующий supporting document сохраняются вместе, а итоговый статус остаётся `insufficient_data`. Подозрение на дубль не становится установленным дублем без resolved operation evidence.
