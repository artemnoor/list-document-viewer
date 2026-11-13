import { mkdir, writeFile } from "node:fs/promises";
import { demoBlueprints } from "../data/demo-blueprints.mjs";

const root = new URL("../data/parser-results/", import.meta.url);

function colLetter(index) {
  let value = index + 1;
  let result = "";
  while (value) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function bbox(page, row, col, colCount) {
  const pageWidth = 595.28;
  const left = 42 + col * ((pageWidth - 84) / colCount);
  const width = (pageWidth - 84) / colCount;
  const top = (page === 1 ? 210 : 96) + row * 25;
  return { l: Number(left.toFixed(2)), t: Number(top.toFixed(2)), r: Number((left + width).toFixed(2)), b: Number((top + 21).toFixed(2)), coord_origin: "TOPLEFT" };
}

function buildDocument(doc) {
  const isXlsx = doc.extension === ".xlsx";
  const logicalTables = [];
  const parts = [];
  const modelParts = [];
  const docTables = [];
  const visualParts = [];
  const provenanceIndex = [];
  const pages = {};
  for (let page = 1; page <= (isXlsx ? 0 : doc.pageCount); page += 1) {
    pages[String(page)] = { page_no: page, size: { width: 595.28, height: 841.89, unit: "pt" }, rotation: 0, coordinate_system: "PDF_POINT_TOPLEFT" };
  }
  const sheets = {};
  let textIndex = 0;

  const inputTables = [
    { id: "document-metadata", caption: "Реквизиты документа", role: "metadata", page: 1, ...(isXlsx ? { sheet: "Сводка", rowStart: 1, colStart: 0 } : {}), header: ["Реквизит", "Значение"], rows: doc.metadata, isMetadata: true },
    ...doc.tables,
  ];

  for (const table of inputTables) {
    const pdfPage = table.page ?? 1;
    const headers = table.header;
    const rows = table.rows;
    const startRow = table.rowStart ?? 1;
    const startCol = table.colStart ?? 1;
    const isSheet = Boolean(table.sheet);
    const tableCells = [];
    const tableRows = [];
    const tableVisualParts = [];
    const rowCountByPage = {};

    for (let rowIndex = -1; rowIndex < rows.length; rowIndex += 1) {
      const values = rowIndex === -1 ? headers : rows[rowIndex];
      const continuation = table.continuationPages?.length ? rowIndex >= Math.ceil(rows.length / 2) : false;
      const currentPage = continuation ? table.continuationPages[0] : pdfPage;
      const logicalRow = { row_id: rowIndex === -1 ? `${table.id}-header` : `${table.id}-r${String(rowIndex + 1).padStart(3, "0")}`, row_index: rowIndex + 1, cells: [] };
      if (rowIndex >= 0) logicalRow.data_row_number = rowIndex + 1;

      values.forEach((textValue, columnIndex) => {
        const absoluteRow = isSheet ? startRow + rowIndex + 1 : rowIndex + 1;
        const absoluteColumn = isSheet ? startCol + columnIndex : columnIndex;
        const cellAddress = isSheet ? `${colLetter(absoluteColumn)}${absoluteRow}` : null;
        const cellId = `${table.id}-${rowIndex < 0 ? "header" : `r${String(rowIndex + 1).padStart(3, "0")}`}-c${String(columnIndex + 1).padStart(2, "0")}`;
        const pageNo = isSheet ? null : currentPage;
        const cellBox = isSheet ? null : bbox(currentPage, rowCountByPage[currentPage] ?? 0, columnIndex, headers.length);
        rowCountByPage[currentPage] = (rowCountByPage[currentPage] ?? 0) + (columnIndex === 0 ? 1 : 0);
        const confidenceKey = `${rowIndex}:${columnIndex}`;
        const confidence = table.confidence?.[confidenceKey] ?? (String(textValue ?? "").includes("?") ? 0.63 : 0.985);
        const provenance = {
          document_id: doc.id,
          source_part_id: cellId,
          source_ref: isSheet ? `${table.sheet}!${cellAddress}` : `#/tables/${docTables.length}/cells/${tableCells.length}`,
          page_no: pageNo,
          ...(isSheet ? { sheet_name: table.sheet, cell_address: cellAddress } : { bbox: cellBox, coordinate_origin: "TOPLEFT", page_size: { width: 595.28, height: 841.89, unit: "pt" } }),
          table_id: table.id,
          row_id: logicalRow.row_id,
          column_index: columnIndex,
          source_text: String(textValue ?? ""),
          confidence,
        };
        const cell = { id: cellId, row: rowIndex + 1, column: columnIndex, column_name: headers[columnIndex], text: String(textValue ?? ""), confidence, provenance };
        if (cellAddress) cell.address = cellAddress;
        if (cellBox) cell.bbox = cellBox;
        if (rowIndex < 0) cell.is_header = true;
        logicalRow.cells.push(cell);
        tableCells.push({ row: rowIndex + 1, column: columnIndex, text: String(textValue ?? ""), row_span: 1, col_span: 1, id: cellId, ...(cellBox ? { bbox: cellBox } : { address: cellAddress }), provenance: [provenance] });
        provenanceIndex.push(provenance);

        const part = { id: cellId, kind: rowIndex < 0 ? "table_header_cell" : "table_cell", text: String(textValue ?? ""), source: isSheet ? "xlsx_native" : "pdf_native", confidence, table_id: table.id, row_id: logicalRow.row_id, column_index: columnIndex, provenance: [provenance] };
        parts.push(part);
        modelParts.push({ kind: "text", label: rowIndex < 0 ? "table_header" : "text", depth: 2, ref: provenance.source_ref, text: String(textValue ?? ""), provenance: [provenance] });
      });
      tableRows.push(values.map((value) => String(value ?? "")));
      if (rowIndex >= 0) logicalTables.push({ table_id: table.id, caption: table.caption, role: table.role, page_no: isSheet ? null : currentPage, sheet_name: isSheet ? table.sheet : null, row: logicalRow });
      if (rowIndex >= 0) tableVisualParts.push({ id: logicalRow.row_id, row_id: logicalRow.row_id, page_no: isSheet ? null : currentPage, cells: logicalRow.cells });
    }

    const tableProv = isSheet ? { page_no: null, sheet_name: table.sheet } : { page_no: pdfPage, bbox: bbox(pdfPage, 0, 0, 1), coord_origin: "TOPLEFT" };
    const nativeTable = { id: table.id, kind: "table", caption: table.caption, role: table.role, rows: tableRows, cells: tableCells, provenance: [tableProv], ...(isSheet ? { sheet_name: table.sheet } : { page_no: pdfPage }) };
    docTables.push(nativeTable);
    modelParts.push({ kind: "table", label: "table", depth: 1, ref: `#/tables/${docTables.length - 1}`, caption: table.caption, text: "", provenance: [tableProv] });
    const logicalTable = { id: table.id, caption: table.caption, role: table.role, headers, rows: tableRows.slice(1).map((values, index) => ({ row_id: `${table.id}-r${String(index + 1).padStart(3, "0")}`, cells: logicalTables.filter((entry) => entry.table_id === table.id)[index]?.row.cells ?? [], ...(isSheet ? { sheet_name: table.sheet } : { page_no: table.continuationPages?.length && index >= Math.ceil(rows.length / 2) ? table.continuationPages[0] : pdfPage }) })), ...(isSheet ? { sheet_name: table.sheet, start_row: startRow, start_column: startCol } : { page_no: pdfPage, continuation_pages: table.continuationPages ?? [] }) };
    doc.logicalTables.push(logicalTable);

    if (isSheet) {
      const sheet = sheets[table.sheet] ?? { sheet_name: table.sheet, dimension: "", tables: [], cells: [] };
      sheet.tables.push(table.id);
      sheet.cells.push(...tableCells.map((cell) => ({ address: cell.address, value: cell.text, formula: null, cached_value: null, number_format: null, provenance: cell.provenance[0] })));
      sheets[table.sheet] = sheet;
    } else {
      const byPage = new Map();
      for (const row of tableVisualParts) {
        const list = byPage.get(row.page_no) ?? [];
        list.push(row);
        byPage.set(row.page_no, list);
      }
      for (const [pageNo, pageRows] of byPage) {
        const flatCells = pageRows.flatMap((row) => row.cells.map((cell) => ({ row: cell.row, column: cell.column, text: cell.text, bbox: cell.bbox, row_span: 1, col_span: 1, id: cell.id })));
        visualParts.push({ id: `${table.id}-p${pageNo}`, kind: "table", table_id: table.id, text: table.caption, source: "pdf_native", provenance: [{ page_no: pageNo, bbox: bbox(pageNo, 0, 0, 1), coord_origin: "TOPLEFT" }], headers, rows: pageRows.map((row) => row.cells.map((cell) => cell.text)), cells: flatCells, classification: "logical_table" });
      }
    }
  }

  for (const [sheetName, sheet] of Object.entries(sheets)) {
    const maxRow = Math.max(...sheet.cells.map((cell) => Number(cell.address.match(/\d+/)?.[0] ?? 0)));
    const maxCol = Math.max(...sheet.cells.map((cell) => cell.address.match(/[A-Z]+/)?.[0].split("").reduce((n, letter) => n * 26 + letter.charCodeAt(0) - 64, 0) ?? 0));
    sheet.dimension = `A1:${colLetter(maxCol - 1)}${maxRow}`;
  }

  const docling = {
    schema_name: "DoclingDocument", version: "1.9.0", name: doc.id,
    origin: { mimetype: isXlsx ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "application/pdf", binary_hash: `demo-${doc.id}`, filename: doc.fileName },
    body: { self_ref: "#/body", children: docTables.map((_, index) => ({ $ref: `#/tables/${index}` })), content_layer: "body", name: "_root_", label: "unspecified" },
    groups: [], texts: parts.map((part, index) => ({ self_ref: `#/texts/${index}`, parent: { $ref: "#/body" }, children: [], content_layer: "body", label: part.kind, prov: part.provenance.map((provenance) => ({ ...(provenance.page_no ? { page_no: provenance.page_no } : {}), ...(provenance.bbox ? { bbox: provenance.bbox } : {}), ...(provenance.cell_address ? { cell_address: provenance.cell_address, sheet_name: provenance.sheet_name } : {}) })), orig: part.text, text: part.text })),
    pictures: [], tables: docTables, key_value_items: [], form_items: [], pages, ...(isXlsx ? { sheets } : {}),
  };
  const fileSize = 100000 + parts.length * 83;
  return {
    parser_output_version: "mock-docling-structured-1.0",
    analysis_version: "audit-2026-11-v1", source_extension: doc.extension, native_structure_version: 4,
    document_id: doc.id, file_name: doc.fileName, title: doc.title, format: doc.format, file_size_bytes: fileSize, demo: true,
    document: docling,
    parts,
    model_parts: modelParts,
    visual_layout: { version: 3, source: isXlsx ? "xlsx_native" : "pdf_native", pages, sheets: isXlsx ? sheets : undefined, parts: visualParts, warnings: [] },
    logical_tables: doc.logicalTables,
    provenance: provenanceIndex,
    page_count: doc.pageCount,
    ...(isXlsx ? { workbook: { sheet_names: Object.keys(sheets), active_sheet: "Реестр", sheets } } : {}),
    status: "complete", warnings: [],
  };
}

await mkdir(root, { recursive: true });
for (const blueprint of demoBlueprints) {
  blueprint.logicalTables = [];
  const result = buildDocument(blueprint);
  const fileUrl = new URL(`${blueprint.id}.json`, root);
  await writeFile(fileUrl, JSON.stringify(result, null, 2) + "\n", "utf8");
}
console.log(`Generated ${demoBlueprints.length} parser-result fixtures.`);
