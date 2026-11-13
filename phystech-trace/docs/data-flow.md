# Путь комплекта документов

1. Frontend создаёт проект и задаёт класс данных. Для конфиденциального проекта разрешение внешней модели отключено.
2. Frontend отправляет документы в Gateway. Gateway проверяет размер каждого файла, задаёт роль (`kfz` или `primary`) и пересылает оригинальные байты в `POST /api/documents` Parser.
3. Parser сохраняет файл на постоянном volume, запускает существующую очередь обработки и возвращает стабильный parser ID. Gateway опрашивает `GET /api/documents/{id}/analysis`, сохраняет полный исходный JSON и добавляет trace metadata: ID проекта, имя и роль файла.
4. Gateway проверяет Parser JSON по `parser-to-extraction-v1` и вызывает Extraction. Адаптер читает фактический parser JSON (`parts`, `model_parts`, `visual_layout`, Docling tables, PDF coordinates и native Office cells). Ответ сохраняет те же `document_id`, исходные/нормализованные значения, `row_id` и provenance.
5. Extraction валидирует вход существующим адаптером и JSON Schema; результат проверяется исходной Zod-схемой и общим `Structured Extraction 1.2.0` контрактом. Результат и input hash сохраняются в PostgreSQL до Linking.
6. Для разрешённого проекта Gateway передаёт весь набор Extraction в настоящий `POST /api/linking-jobs`. Linking проверяет пакет, создаёт durable BullMQ job и возвращает ID. Gateway опрашивает прогресс до получения результата.
7. Link evidence содержит исходный `document_id`, JSON path, raw и normalized values, row ID и `provenance`. Gateway сохраняет Linking result целиком и сопоставляет parser ID с исходным файлом.
8. Frontend показывает этапы, ошибки, частичные результаты, распознанные строки, спорные связи и источник. Для PDF он запрашивает изображение страницы у Parser и накладывает сохранённый bbox. Для XLSX показывает лист и адрес ячейки. Оригинальный файл открывается через Gateway.
9. Подтверждение или отклонение связи проходит через Gateway в существующий `PATCH /api/linking-runs/{runId}/links/{linkId}`. Linking атомарно сохраняет решение специалиста; Gateway обновляет результат проекта.

Состояние хранится на уровне документа. Ошибка одного файла не удаляет успешные результаты остальных. Повтор Parser/Extraction/Linking использует успешно сохранённые результаты ранних этапов. Тайм-аут, несовместимая схема, повторный ID и отсутствие ключа остаются диагностируемыми ошибками.
