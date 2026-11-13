# Сквозной тест Phystech Trace

Тест работает с уже запущенным Docker Compose через публичные HTTP API и использует только синтетические документы: PDF и PNG из `backend/tests/complex_fixtures`, а также временные XLSX и DOCX с вымышленными данными.

```powershell
python tests/e2e/run_e2e.py
```

Код возврата `0` означает, что прошли Parser, Extraction и Linking, а source evidence разрешается до исходного файла. Код `2` означает, что Parser и Extraction прошли, но Linking не завершил реальный модельный этап; в таком случае тест проверяет диагностируемую ошибку и повторный запуск без потери успешных результатов. Любая другая ошибка останавливает тест.

Отчёт последнего запуска сохраняется в `tests/e2e/results/latest-run.json`. Проверенный синтетический отчёт включён в репозиторий; новый запуск заменит его.

Если Gateway остановил этап Linking после ошибки API, можно повторить только его на сохранённом проекте:

```powershell
python tests/e2e/retry_linking.py --project-id <project-id>
```

Этот сценарий проверяет сохранность Parser/Extraction IDs, повтор через Gateway, реальный вызов Polza и разрешение каждого evidence path до исходного значения и provenance.

Для ограниченной live-проверки модели используйте три синтетических документа PDF/XLSX/DOCX с одной заведомо общей строкой:

```powershell
python tests/e2e/run_e2e.py --compact-linking
python tests/e2e/review_decisions.py --project-id <project-id>
python tests/e2e/verify_saved_project.py --project-id <project-id>
```

Компактный профиль проверяет ожидаемые связи отчёта, акта и реестра, включая совпадающую строку работ. Скрипт review подтверждает одну связь и отклоняет другую через Gateway, затем проверяет сохранение решений и неизменность evidence. `verify_saved_project.py` повторно проверяет сохранённые связи, исходники и provenance без нового вызова модели. Стандартный профиль дополнительно загружает PDF/PNG fixtures и дубликат изображения; он шире и может превысить контекст или лимит ответа live-модели. Оба профиля используют только синтетические данные.
