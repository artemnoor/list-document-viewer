# Original Document Parser samples

These JSON files are copied unmodified from the test corpus of [artemnoor/list-document-viewer](https://github.com/artemnoor/list-document-viewer). They are parser outputs only; this project does not run OCR or Docling.

- `document-parser-native-xlsx.analysis.json` — `backend/tests/corpus/http-store/02_04_Ведомость_ЗП_Апрель_2026.xlsx.analysis.json`
- `document-parser-native-pdf.analysis.json` — `backend/tests/corpus/http-store/15_Акт_ADM-75_15-05-2026.pdf.analysis.json`
- `document-parser-native-pdf.layout.json` — matching PDF native visual layout output

The adapter tests consume the original JSON shapes directly, including `parts`, `model_parts`, Docling table cells, PDF provenance and separate layout data.
