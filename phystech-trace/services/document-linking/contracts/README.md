# Контракты данных

Входной контракт сверяется с актуальным upstream репозиторием Structured Extraction; зафиксированный commit и schema version хранятся в `versions.json`. API принимает массив результатов либо envelope `{ "extraction": result }`. Неизвестные добавочные поля major 1 сохраняются.

- `input.schema.json` — совместимый вход Structured Extraction 1.2.0.
- `output.schema.json` — расширяемый граф Document Linking 1.2.0. `relationship_type` — открытая строка; недействительные технически предложения хранятся в `link_validation_diagnostics`, отдельно от графа.
- `../prompts/document-linking-system.md` — системная инструкция модели.
- `../fixtures/upstream-structured-extraction-1.2.0/` — реальные входы Structured Extraction 1.2.0.
- `../fixtures/demo-structured-extraction/` — пользовательские сценарии интерфейса.

Каждая связь сохраняет документные и строковые ID, объяснение, статус, уверенность и технические ссылки на исходные пути/значения/provenance. Метаданные сохраняют модель, провайдера, вызовы, usage и стоимость, когда провайдер её возвращает. Набор независимой экспертной разметки для расчёта precision/recall/F1 пока не включён.
