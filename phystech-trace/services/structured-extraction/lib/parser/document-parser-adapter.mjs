const HEADER_WORDS = /код|идентифик|артикул|наимен|описан|показател|работ|единиц|колич|объем|объём|план|факт|сумм|стоим|цен|итого|основан|дата|ставк|тариф/i;

const asString = (value) => value == null ? "" : typeof value === "string" ? value : String(value);
const clean = (value) => asString(value).replace(/[\u00a0\u202f]/g, " ").trim();
const canonical = (value) => clean(value).toLocaleLowerCase("ru-RU").replace(/ё/g, "е").replace(/[^\p{L}\p{N}]+/gu, " ").trim();

function hashId(value) {
  let hash = 2166136261;
  for (const char of String(value)) hash = Math.imul(hash ^ char.codePointAt(0), 16777619);
  return (hash >>> 0).toString(36);
}

function slug(value) {
  return clean(value).toLocaleLowerCase("ru-RU").replace(/ё/g, "е").normalize("NFKD")
    .replace(/[^a-zа-я0-9]+/gi, "-").replace(/^-|-$/g, "").slice(0, 48) || "document";
}

function unwrap(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) return input;
  const parsed = input.parser_json ?? input.analysis ?? input.analysis_json ?? input;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return parsed;
  const layout = input.layout_json ?? input.visual_layout ?? input.layout ?? parsed.visual_layout;
  if (layout && typeof layout === "object" && (Array.isArray(layout.parts) || layout.pages || layout.visual_layout)) {
    const visualLayout = layout.visual_layout ?? layout;
    return { ...parsed, visual_layout: visualLayout };
  }
  return parsed;
}

function documentIdOf(parsed) {
  const existing = parsed.document_id ?? parsed.document?.origin?.document_id ?? parsed.document?.name;
  if (existing != null && clean(existing)) return String(existing);
  const filename = parsed.document?.origin?.filename ?? parsed.file_name ?? parsed.filename ?? parsed.title ?? "document-parser-result";
  const fingerprint = parsed.document?.origin?.binary_hash ?? parsed.document?.origin?.sha256 ?? filename;
  return `dp-${slug(filename)}-${hashId(fingerprint)}`;
}

function originPageSize(parsed, pageNo) {
  const visual = parsed.visual_layout ?? parsed.layout ?? {};
  const page = visual.pages?.[String(pageNo)] ?? visual.pages?.[pageNo] ?? parsed.document?.pages?.[String(pageNo)] ?? parsed.document?.pages?.[pageNo];
  const size = page?.size ?? page?.unrotated_size ?? page;
  if (!size || !Number.isFinite(Number(size.width)) || !Number.isFinite(Number(size.height))) return null;
  return {
    width: Number(size.width), height: Number(size.height),
    unit: String(size.unit ?? page?.unit ?? "pt"),
    ...(page?.rotation != null ? { rotation: Number(page.rotation) } : {}),
  };
}

function firstProvenance(value) {
  const raw = value?.provenance ?? value?.prov;
  return Array.isArray(raw) ? raw.find((item) => item && typeof item === "object") ?? null : raw ?? null;
}

function partText(part) {
  if (!part || typeof part !== "object") return "";
  if (part.display_value !== undefined && part.display_value !== null) return asString(part.display_value);
  if (part.cached_value !== undefined && part.cached_value !== null) return asString(part.cached_value);
  if (part.value !== undefined && part.value !== null) return asString(part.value);
  if (part.text !== undefined && part.text !== null) return asString(part.text);
  if (part.content !== undefined && part.content !== null) return asString(part.content);
  if (part.fragment !== undefined && part.fragment !== null) return asString(part.fragment);
  if (part.orig !== undefined && part.orig !== null) return asString(part.orig);
  return asString(part.formula);
}

function sourceReference(value) {
  const ref = value?.source_ref ?? value?.cref ?? (typeof value?.ref === "string" ? value.ref : value?.ref?.cref) ?? value?.self_ref;
  return typeof ref === "string" && ref.trim() ? ref.trim() : null;
}

function provenanceItems(value) {
  const raw = Array.isArray(value) ? value : value?.provenance ?? value?.prov;
  if (Array.isArray(raw)) return raw.filter((item) => item && typeof item === "object");
  if (raw && typeof raw === "object") return [raw];
  const hasNativeLocator = value && typeof value === "object" && [
    "bbox", "bounding_box", "page_no", "page", "sheet_name", "sheet", "address", "cell_address", "coordinate", "source_ref", "cref", "ref", "self_ref",
  ].some((key) => value[key] != null);
  return hasNativeLocator ? [value] : [];
}

function normalizeBBox(value) {
  if (Array.isArray(value) && value.length >= 4) {
    const [l, t, r, b] = value;
    return { l: Number(l), t: Number(t), r: Number(r), b: Number(b) };
  }
  if (!value || typeof value !== "object") return null;
  if ([value.l, value.t, value.r, value.b].every((item) => Number.isFinite(Number(item)))) {
    return { l: Number(value.l), t: Number(value.t), r: Number(value.r), b: Number(value.b), ...(value.coord_origin ? { coord_origin: String(value.coord_origin) } : {}) };
  }
  const x = Number(value.x ?? value.left), y = Number(value.y ?? value.top);
  const width = Number(value.width ?? value.w), height = Number(value.height ?? value.h);
  if ([x, y, width, height].every(Number.isFinite)) return { l: x, t: y, r: x + width, b: y + height, ...(value.coord_origin ? { coord_origin: String(value.coord_origin) } : {}) };
  return null;
}

function rowValues(row) {
  if (Array.isArray(row)) return row;
  const values = row?.cells ?? row?.values ?? row?.items ?? [];
  if (Array.isArray(values)) return values;
  if (values && typeof values === "object") return Object.entries(values).map(([key, value]) => value && typeof value === "object" ? { column_name: key, ...value } : ({ column_name: key, value }));
  return [];
}

function rowCollection(table) {
  const fragments = Array.isArray(table?.fragments) ? table.fragments.filter((fragment) => fragment && typeof fragment === "object") : [];
  const sources = [{ ...table, fragments: undefined }, ...fragments];
  const rows = [];
  for (const [fragmentIndex, fragment] of sources.entries()) {
    const fragmentRows = Array.isArray(fragment.rows) ? fragment.rows : Array.isArray(fragment.values) ? fragment.values : [];
    for (const [rowIndex, row] of fragmentRows.entries()) rows.push({
      raw: row,
      fragment,
      fragment_index: fragmentIndex,
      source_row_index: row?.source_row_index ?? row?.index ?? rowIndex,
    });
  }
  return rows;
}

function colLetters(oneBased) {
  let n = oneBased;
  let result = "";
  while (n > 0) { const remainder = (n - 1) % 26; result = String.fromCharCode(65 + remainder) + result; n = Math.floor((n - 1) / 26); }
  return result;
}

function parseCellAddress(value) {
  const match = clean(value).match(/^\$?([A-Z]+)\$?(\d+)$/i);
  if (!match) return null;
  let column = 0;
  for (const letter of match[1].toUpperCase()) column = column * 26 + letter.charCodeAt(0) - 64;
  return { column, row: Number(match[2]) };
}

function parseCellRange(value) {
  const [first, last = first] = clean(value).split(":");
  const start = parseCellAddress(first);
  const end = parseCellAddress(last);
  if (!start || !end) return null;
  return { start_row: Math.min(start.row, end.row), end_row: Math.max(start.row, end.row), start_column: Math.min(start.column, end.column), end_column: Math.max(start.column, end.column) };
}

function makeProvenance(source, options) {
  const { documentId, elementId, text, fallback, pageNo, sheetName, cellAddress, tableId, rowId, column } = options;
  if (source?._synthetic === true) return null;
  const sourceList = provenanceItems(source);
  const fallbackList = provenanceItems(fallback);
  const provList = sourceList.length ? sourceList : fallbackList;
  const distinctPages = [...new Set(provList.map((item) => Number(item?.page_no)).filter(Number.isFinite))];
  const ambiguousPage = !sourceList.length && distinctPages.length > 1;
  const input = sourceList[0] ?? fallbackList[0] ?? {};
  const sourcePage = ambiguousPage ? null : input.page_no ?? source?.page_no ?? source?.page ?? source?.slide ?? fallback?.page_no ?? pageNo ?? null;
  const sourceSheet = input.sheet_name ?? source?.sheet_name ?? source?.sheet ?? fallback?.sheet_name ?? sheetName ?? null;
  const sourceCell = input.cell_address ?? input.address ?? source?.cell_address ?? source?.address ?? source?.coordinate ?? fallback?.cell_address ?? cellAddress ?? null;
  const rawBBox = ambiguousPage ? null : input.bbox ?? input.bounding_box ?? source?.bbox ?? source?.bounding_box ?? fallback?.bbox ?? null;
  const normalizedBBox = normalizeBBox(rawBBox);
  const coordinateOrigin = input.coordinate_origin ?? normalizedBBox?.coord_origin ?? source?.coordinate_origin ?? null;
  const pageSize = input.page_size ?? originPageSize(options.parsed, sourcePage) ?? fallback?.page_size ?? null;
  const confidenceValue = input.confidence ?? source?.confidence ?? fallback?.confidence;
  const confidence = confidenceValue != null && Number.isFinite(Number(confidenceValue)) ? Math.max(0, Math.min(1, Number(confidenceValue))) : null;
  const ref = input.source_ref ?? sourceReference(source) ?? sourceReference(fallback) ?? null;
  const hasLocation = Boolean(input && Object.keys(input).length) || ref || sourcePage != null || sourceSheet || sourceCell || normalizedBBox || tableId || rowId || column != null;
  if (!hasLocation) return null;
  const provenance = {
    document_id: documentId,
    source_part_id: elementId,
    ...(ref ? { source_ref: String(ref) } : {}),
    page_no: sourcePage == null ? null : Number(sourcePage),
    sheet_name: sourceSheet == null ? null : String(sourceSheet),
    cell_address: sourceCell == null ? null : String(sourceCell),
    bbox: normalizedBBox,
    coordinate_origin: coordinateOrigin == null ? null : String(coordinateOrigin),
    page_size: pageSize,
    ...(tableId ? { table_id: String(tableId) } : {}),
    ...(rowId ? { row_id: String(rowId) } : {}),
    ...(column != null ? { column_index: Number(column) } : {}),
    source_text: String(input.source_text ?? text ?? ""),
    confidence,
    source_available: source?.source_available !== false && source?._synthetic !== true && fallback?.source_available !== false && fallback?._synthetic !== true,
    ...(input.charspan ?? source?.charspan ? { charspan: input.charspan ?? source?.charspan } : {}),
    ...(input.origin ?? input.coordinate_system ? { source_coordinate_system: String(input.origin ?? input.coordinate_system) } : {}),
    ...(provList.length > 1 ? { provenance_alternates: provList.slice(1).map((item) => ({ page_no: item.page_no ?? null, bbox: normalizeBBox(item.bbox ?? item.bounding_box), coordinate_origin: item.coordinate_origin ?? item.bbox?.coord_origin ?? null, source_ref: sourceReference(item) })) } : {}),
  };
  if (provenance.bbox && provenance.page_size && /BOTTOMLEFT/i.test(provenance.coordinate_origin ?? provenance.bbox.coord_origin ?? "")) {
    const { l, t, r, b } = provenance.bbox;
    const height = provenance.page_size.height;
    provenance.bbox_top_left = { l, t: height - Math.max(t, b), r, b: height - Math.min(t, b), coord_origin: "TOPLEFT" };
  }
  return provenance;
}

function inferRole(caption, headers, rows) {
  const label = canonical(caption);
  const headerText = canonical(headers.join(" "));
  if (/реквизит|стороны|подписи|банковские реквизит/.test(label)) return "metadata";
  if (/справочник|классификатор|перечень единиц/.test(label)) return "reference";
  if (/приложени|дополнительные материалы/.test(label)) return "appendix";
  if (/итоговые показатели|сводные показатели|сводная таблица|итого по документу/.test(label)) return "summary";
  if (/оплат|платеж|платёж|этап/.test(label)) return "payment_schedule";
  if (/измен|новая редакция|редакция до/.test(label)) return "amendments";
  if (headers.length <= 2 && rows.length && rows.every((row) => {
    const cells = row.cells ?? [];
    return cells.filter((cell) => clean(cell.text)).length <= 2 && /:/.test(cells[0]?.text ?? "");
  })) return "metadata";
  const identity = /идентифик|код|артикул|номер позиции/.test(headerText);
  const description = /наимен|описан|содержание работ|показател/.test(headerText);
  const quantities = /колич|кол во|объем|план|факт/.test(headerText);
  const units = /единиц|ед изм/.test(headerText);
  const amounts = /цена|стоимост|сумм/.test(headerText);
  const itemCaption = /строк|позици|расшифров|перечень работ|реестр/.test(label);
  if (rows.length && ((identity && description) || (itemCaption && (quantities || units || amounts)) || (description && quantities && amounts))) return "line_items";
  return "table";
}

function normalizeEnvelopeTables(parsed, state) {
  const rawTables = Array.isArray(parsed.logical_tables) ? parsed.logical_tables : [];
  return rawTables.map((table, tableIndex) => normalizeExplicitTable(table, tableIndex, state, "logical_tables"));
}

function normalizeExplicitTable(table, tableIndex, state, sourceType) {
  const tableId = String(table.id ?? table.table_id ?? table.ref ?? `${sourceType}-table-${tableIndex + 1}`);
  const caption = String(table.caption ?? table.title ?? table.text ?? table.name ?? `Таблица ${tableIndex + 1}`);
  const tableRef = sourceReference(table) ?? (sourceType === "logical_tables" ? `#/logical_tables/${tableIndex}` : sourceType === "native_parts" ? `#/parts/${table.index ?? tableIndex}` : null);
  const tableProv = table.provenance ?? table.prov ?? null;
  const sourceRows = rowCollection(table);
  let headers = [];
  const rawHeaders = table.headers ?? table.header_rows ?? table.header_cells ?? [];
  if (Array.isArray(rawHeaders) && rawHeaders.length) {
    if (Array.isArray(rawHeaders[0])) {
      const width = Math.max(...rawHeaders.map((row) => rowValues(row).length), 0);
      headers = Array.from({ length: width }, (_, column) => rawHeaders.map((row) => {
        const value = rowValues(row)[column];
        return typeof value === "object" && value !== null ? partText(value) : asString(value);
      }).map(clean).filter(Boolean).filter((value, index, all) => all.indexOf(value) === index).join(" · "));
    } else headers = rawHeaders.map((item) => typeof item === "object" ? partText(item) : asString(item));
  }
  let rawHeaderCells = Array.isArray(table.header_cells) ? table.header_cells : [];
  let headerSource = table;
  if (!headers.length && sourceRows.length) {
    const firstCells = rowValues(sourceRows[0].raw);
    const explicitHeader = sourceRows[0].raw?.is_header === true || sourceRows[0].raw?.header === true || firstCells.some((cell) => cell?.column_header === true);
    const inferHeader = explicitHeader || sourceType !== "logical_tables";
    if (inferHeader) {
      headers = firstCells.map((cell) => typeof cell === "object" ? partText(cell) : asString(cell));
      rawHeaderCells = firstCells;
      headerSource = sourceRows[0].fragment;
      sourceRows.shift();
    }
  }
  const maxDataWidth = Math.max(headers.length, ...sourceRows.map(({ raw }) => rowValues(raw).length), 0);
  if (!headers.length && maxDataWidth) headers = Array.from({ length: maxDataWidth }, (_, column) => `Колонка ${column + 1}`);
  if (headers.length < maxDataWidth) headers = [...headers, ...Array.from({ length: maxDataWidth - headers.length }, (_, index) => `Колонка ${headers.length + index + 1}`)];
  const headerElements = headers.map((header, column) => {
    const nativeCell = table.cells?.find((item) => Number(item.row) === 0 && Number(item.column) === column);
    const source = rawHeaderCells[column] && typeof rawHeaderCells[column] === "object" ? { ...rawHeaderCells[column] } : nativeCell ? { ...nativeCell } : { text: header };
    if (tableRef && !sourceReference(source)) source.source_ref = `${tableRef}/headers/${column}`;
    const cell = state.makeCell(source, { tableId, rowIndex: -1, column, fallback: headerSource?.provenance ?? tableProv, sheetName: table.sheet_name ?? table.sheet, pageNo: table.page_no ?? table.page ?? table.slide });
    cell.text ||= header;
    return cell;
  });
  const rows = sourceRows.map(({ raw: rawRow, fragment, fragment_index: fragmentIndex, source_row_index: originalRow }, rowIndex) => {
    const values = rowValues(rawRow);
    const sourceRowId = rawRow?.row_id ?? rawRow?.id ?? `${tableId}-p${rawRow?.page_no ?? fragment?.page_no ?? fragment?.page ?? fragmentIndex + 1}-r${String(originalRow + 1).padStart(3, "0")}`;
    const rowPage = rawRow?.page_no ?? rawRow?.page ?? fragment?.page_no ?? fragment?.page ?? firstProvenance(fragment)?.page_no ?? table.page_no ?? table.page ?? table.slide ?? null;
    const rowSheet = rawRow?.sheet_name ?? rawRow?.sheet ?? fragment?.sheet_name ?? fragment?.sheet ?? table.sheet_name ?? table.sheet ?? null;
    const sourceCells = fragment?.cells ?? table.cells ?? [];
    return {
      row_id: String(sourceRowId),
      page_no: rowPage == null ? null : Number(rowPage),
      sheet_name: rowSheet == null ? null : String(rowSheet),
      cells: Array.from({ length: Math.max(headers.length, values.length) }, (_, column) => {
        const rowIndexInSource = Number(rawRow?.source_row_index ?? originalRow);
        const nativeCell = sourceCells.find((item) => Number(item.row ?? item.start_row_offset_idx) === rowIndexInSource && Number(item.column ?? item.start_col_offset_idx) === column);
        const rawCell = values[column];
        let source = rawCell && typeof rawCell === "object" ? { ...rawCell } : { text: rawCell };
        if (nativeCell) source = { ...source, ...nativeCell, text: partText(source) || nativeCell.text };
        const fragmentRef = sourceReference(fragment) ?? (tableRef ? fragmentIndex === 0 ? tableRef : `${tableRef}/fragments/${fragmentIndex - 1}` : null);
        let rowValuePath = `rows/${originalRow}/values/${column}`;
        if (Array.isArray(rawRow)) rowValuePath = `rows/${originalRow}/${column}`;
        else if (Array.isArray(rawRow?.cells)) rowValuePath = `rows/${originalRow}/cells/${column}`;
        else if (rawRow?.cells && typeof rawRow.cells === "object") rowValuePath = `rows/${originalRow}/cells/${Object.keys(rawRow.cells)[column] ?? column}`;
        else if (rawRow?.values && typeof rawRow.values === "object" && !Array.isArray(rawRow.values)) rowValuePath = `rows/${originalRow}/values/${Object.keys(rawRow.values)[column] ?? column}`;
        if (fragmentRef && !sourceReference(source)) source.source_ref = `${fragmentRef}/${rowValuePath}`;
        const covering = !nativeCell && sourceCells.find((item) => {
          const r = Number(item.row ?? item.start_row_offset_idx ?? 0), c = Number(item.column ?? item.start_col_offset_idx ?? 0);
          return rowIndexInSource >= r && rowIndexInSource < r + Number(item.row_span ?? 1) && column >= c && column < c + Number(item.col_span ?? 1);
        });
        if (covering) source = { ...source, text: "", merged_from: { row: covering.row ?? covering.start_row_offset_idx, column: covering.column ?? covering.start_col_offset_idx } };
        return state.makeCell(source, {
        tableId, rowId: String(sourceRowId), rowIndex, column,
        fallback: rawRow?.provenance ?? fragment?.provenance ?? tableProv, sheetName: rowSheet, pageNo: rowPage,
      });
      }),
    };
  });
  const role = String(table.role ?? inferRole(caption, headers, rows));
  return {
    id: tableId, caption, role, headers, header_cells: headerElements, rows,
    page_no: table.page_no ?? table.page ?? table.slide ?? firstProvenance(table)?.page_no ?? null,
    page_numbers: [...new Set([table.page_no, table.page, table.slide, ...(rows.map((row) => row.page_no))].filter((value) => value != null && Number.isFinite(Number(value))).map(Number))],
    sheet_name: table.sheet_name ?? table.sheet ?? null,
    provenance: tableProv,
    merged_ranges: table.merged_ranges ?? table.merged ?? [],
    source_type: sourceType,
    source_ref: tableRef,
    fragment_count: Array.isArray(table.fragments) ? table.fragments.length : 0,
    source_rows_count: rows.length,
  };
}

function tableGrid(table) {
  const data = table?.data ?? {};
  const declaredRows = Number(data.num_rows ?? table.num_rows ?? 0);
  const declaredCols = Number(data.num_cols ?? table.num_cols ?? 0);
  const sourceCells = Array.isArray(data.table_cells) ? data.table_cells : [];
  if (sourceCells.length) {
    const inferredRows = Math.max(...sourceCells.map((cell) => Number(cell.end_row_offset_idx ?? Number(cell.start_row_offset_idx ?? 0) + Number(cell.row_span ?? 1))), 0);
    const inferredCols = Math.max(...sourceCells.map((cell) => Number(cell.end_col_offset_idx ?? Number(cell.start_col_offset_idx ?? 0) + Number(cell.col_span ?? 1))), 0);
    const maxRows = Math.min(Math.max(declaredRows, inferredRows, 1), 5000);
    const maxCols = Math.min(Math.max(declaredCols, inferredCols, 1), 500);
    const grid = Array.from({ length: maxRows }, () => Array.from({ length: maxCols }, () => null));
    for (const cell of sourceCells.slice(0, 100000)) {
      const row = Number(cell.start_row_offset_idx ?? 0);
      const col = Number(cell.start_col_offset_idx ?? 0);
      if (row < 0 || col < 0 || row >= maxRows || col >= maxCols) continue;
      if (!grid[row][col]) grid[row][col] = cell;
    }
    return grid;
  }
  if (Array.isArray(data.grid)) return data.grid.slice(0, 5000).map((row) => (Array.isArray(row) ? row.slice(0, 500) : []));
  if (Array.isArray(table.rows)) return table.rows;
  return [];
}

function normalizeDoclingTable(table, index, state, sourceType) {
  const tableId = String(table.id ?? table.table_id ?? table.ref ?? table.self_ref ?? `${sourceType}-table-${index + 1}`);
  const caption = String(table.caption ?? table.name ?? table.text ?? table.label ?? `Таблица ${index + 1}`);
  const grid = tableGrid(table);
  const sourceCells = Array.isArray(table.data?.table_cells) ? table.data.table_cells : [];
  const prov = table.provenance ?? table.prov ?? null;
  const sourcePages = [...new Set((Array.isArray(prov) ? prov : [prov]).map((item) => Number(item?.page_no)).filter(Number.isFinite))];
  const singlePage = sourcePages.length === 1 ? sourcePages[0] : null;
  const headerRows = new Set();
  for (let rowIndex = 0; rowIndex < grid.length; rowIndex++) {
    if (grid[rowIndex].some((cell) => cell && typeof cell === "object" && cell.column_header)) headerRows.add(rowIndex);
  }
  if (!headerRows.size && grid.length) {
    const firstNonEmpty = grid.findIndex((row) => row.some((cell) => clean(typeof cell === "object" ? partText(cell) : cell)));
    if (firstNonEmpty >= 0) headerRows.add(firstNonEmpty);
  }
  const headerIndexes = [...headerRows].sort((a, b) => a - b);
  const firstHeader = headerIndexes[0] ?? 0;
  const width = Math.max(Number(table.data?.num_cols ?? table.num_cols ?? 0), ...grid.map((row) => row.length), 0);
  const headerCells = Array.from({ length: width }, (_, column) => {
    const textParts = [];
    const origins = [];
    for (const rowIndex of headerIndexes) {
      let cell = grid[rowIndex]?.[column];
      if (!cell && sourceCells.length) cell = sourceCells.find((candidate) => {
        const r = Number(candidate.start_row_offset_idx ?? 0);
        const c = Number(candidate.start_col_offset_idx ?? 0);
        return rowIndex >= r && rowIndex < r + Number(candidate.row_span ?? 1) && column >= c && column < c + Number(candidate.col_span ?? 1);
      });
      if (!cell) continue;
      const startRow = Number(cell.start_row_offset_idx ?? rowIndex);
      const startColumn = Number(cell.start_col_offset_idx ?? column);
      origins.push({ cell, rowIndex: startRow, column: startColumn });
      const value = clean(typeof cell === "object" ? partText(cell) : cell);
      if (value && textParts.at(-1) !== value) textParts.push(value);
    }
    const text = textParts.join(" · ");
    const representative = origins.at(-1) ?? null;
    const source = representative?.cell ?? { text };
    const headerCell = state.makeCell(source, { tableId, rowIndex: representative?.rowIndex ?? firstHeader, column: representative?.column ?? column, fallback: prov });
    headerCell.text = text;
    const sourceIds = origins.map(({ cell: origin, rowIndex, column: sourceColumn }) => state.makeCell(origin, { tableId, rowIndex, column: sourceColumn, fallback: prov }).id);
    headerCell.source_element_ids = [...new Set([headerCell.id, ...sourceIds])];
    return headerCell;
  });
    const rows = [];
  for (let rowIndex = 0; rowIndex < grid.length; rowIndex++) {
    if (headerRows.has(rowIndex) || rowIndex < firstHeader) continue;
    const rawRow = grid[rowIndex] ?? [];
    const rowId = `${tableId}-r${String(rowIndex + 1).padStart(3, "0")}`;
    const cells = Array.from({ length: width }, (_, column) => {
      let source = rawRow[column];
      if (!source && sourceCells.length) source = sourceCells.find((candidate) => {
        const r = Number(candidate.start_row_offset_idx ?? 0);
        const c = Number(candidate.start_col_offset_idx ?? 0);
        return rowIndex >= r && rowIndex < r + Number(candidate.row_span ?? 1) && column >= c && column < c + Number(candidate.col_span ?? 1);
      });
      const anchorRow = Number(source?.start_row_offset_idx ?? rowIndex);
      const anchorColumn = Number(source?.start_col_offset_idx ?? column);
      const merged = source && typeof source === "object" && (anchorRow !== rowIndex || anchorColumn !== column);
      const cell = state.makeCell(merged ? { ...source, text: "", merged_from: { row: anchorRow, column: anchorColumn } } : source ?? { text: "", _synthetic: true }, {
        tableId, rowId, rowIndex, column, fallback: prov,
      });
      if (merged) cell.text = "";
      return cell;
    });
    const cellPages = [...new Set(cells.map((cell) => cell.page_no).filter(Number.isFinite))];
    const rowPage = cellPages.length === 1 ? cellPages[0] : singlePage;
    rows.push({ row_id: rowId, page_no: rowPage, sheet_name: null, cells });
  }
  const headers = headerCells.map((cell) => cell.text);
  const sourceMerged = Array.isArray(table.merged) ? table.merged : [];
  const role = table.role ?? inferRole(caption, headers, rows);
  return {
    id: tableId, caption, role, headers, header_cells: headerCells, rows,
    page_no: singlePage, page_numbers: sourcePages, sheet_name: table.sheet_name ?? null,
    provenance: prov, merged_ranges: sourceMerged,
    merged_cells: grid.flatMap((row, rowIndex) => row.flatMap((cell, column) => cell && typeof cell === "object" && (Number(cell.row_span ?? 1) > 1 || Number(cell.col_span ?? 1) > 1) ? [{ row: rowIndex, column, row_span: Number(cell.row_span ?? 1), col_span: Number(cell.col_span ?? 1), text: partText(cell) }] : [])),
    source_type: sourceType,
    source_ref: table.ref ?? table.self_ref ?? null,
  };
}

function officeTables(parsed, state) {
  const parts = Array.isArray(parsed.parts) ? parsed.parts : [];
  const sheets = parts.filter((part) => part?.kind === "sheet");
  const cells = parts.filter((part) => part?.kind === "cell" && (part.coordinate || part.address));
  if (!cells.length) return [];
  const grouped = new Map();
  for (const cell of cells) {
    const sheet = String(cell.sheet ?? "Лист1");
    if (!grouped.has(sheet)) grouped.set(sheet, []);
    const address = parseCellAddress(cell.coordinate ?? cell.address);
    if (!address) continue;
    grouped.get(sheet).push({ ...cell, _row: Number(cell.row ?? address.row), _column: Number(cell.column ?? address.column), _address: cell.coordinate ?? cell.address });
  }
  const result = [];
  for (const [sheetName, sheetCells] of grouped) {
    const byRow = new Map();
    for (const cell of sheetCells) {
      if (!byRow.has(cell._row)) byRow.set(cell._row, new Map());
      byRow.get(cell._row).set(cell._column, cell);
    }
    const candidateRows = [...byRow.keys()].sort((a, b) => a - b).map((row) => {
      const rowCells = [...byRow.get(row).values()].sort((a, b) => a._column - b._column);
      const nonEmpty = rowCells.filter((cell) => clean(partText(cell))).length;
      const keywordCount = rowCells.filter((cell) => HEADER_WORDS.test(partText(cell))).length;
      const label = canonical(rowCells.map(partText).join(" "));
      const isTotal = /(^|\s)(итого|всего|total)(\s|$)/.test(label);
      return { row, rowCells, nonEmpty, keywordCount, isTotal };
    });
    const headers = candidateRows.filter((item) => item.nonEmpty >= 2 && !item.isTotal && item.keywordCount >= 2);
    if (!headers.length) {
      const fallback = candidateRows.find((item) => item.nonEmpty >= 2);
      if (fallback) headers.push(fallback);
    }
    for (const [tableIndex, header] of headers.entries()) {
      const nextHeaderRow = headers[tableIndex + 1]?.row ?? Infinity;
      const blockCells = sheetCells.filter((cell) => cell._row >= header.row && cell._row < nextHeaderRow);
      const minCol = Math.min(...header.rowCells.map((cell) => cell._column));
      const maxCol = Math.max(...blockCells.map((cell) => cell._column));
      const tableId = `xlsx-${slug(sheetName)}-${tableIndex + 1}`;
      const sheet = sheets.find((item) => item.name === sheetName);
      const mergedRanges = (sheet?.merged ?? []).map((range) => ({ address: String(range), ...parseCellRange(range) })).filter((range) => range.start_row);
      const headerSources = Array.from({ length: maxCol - minCol + 1 }, (_, offset) => {
        const column = minCol + offset;
        const candidates = [];
        const direct = byRow.get(header.row)?.get(column);
        if (direct && clean(partText(direct))) candidates.push(direct);
        for (const range of mergedRanges) {
          const coversColumn = column >= range.start_column && column <= range.end_column;
          const nearHeader = range.start_row < header.row && range.end_row >= header.row - 1 && range.start_row >= header.row - 2
            || range.start_row === header.row && range.end_row >= header.row;
          const broadTitle = range.start_column <= minCol && range.end_column >= maxCol && range.end_column > range.start_column;
          if (!coversColumn || !nearHeader || broadTitle) continue;
          const anchor = byRow.get(range.start_row)?.get(range.start_column);
          if (anchor && clean(partText(anchor)) && !candidates.some((item) => item.coordinate === anchor.coordinate)) candidates.push(anchor);
        }
        candidates.sort((a, b) => a._row - b._row || a._column - b._column);
        return candidates;
      });
      const headersText = headerSources.map((sources) => [...new Set(sources.map(partText).map(clean).filter(Boolean))].join(" · "));
      const headerCells = Array.from({ length: headersText.length }, (_, offset) => {
        const candidates = headerSources[offset];
        const source = candidates.at(-1) ?? byRow.get(header.row)?.get(minCol + offset) ?? { text: "", _synthetic: true };
        const cell = state.makeCell(source, { tableId, rowIndex: header.row, column: offset, sheetName, cellAddress: source.coordinate ?? source._address });
        cell.text = headersText[offset];
        cell.source_element_ids = [...new Set([cell.id, ...candidates.map((item) => state.makeCell(item, { tableId, rowIndex: item._row, column: item._column - minCol, sheetName, cellAddress: item.coordinate ?? item._address }).id)])];
        return cell;
      });
      const rows = [];
      for (const rowNumber of [...byRow.keys()].sort((a, b) => a - b)) {
        if (rowNumber <= header.row || rowNumber >= nextHeaderRow) continue;
        const rowMap = byRow.get(rowNumber);
        const cellsInRow = Array.from({ length: headersText.length }, (_, offset) => {
          const column = minCol + offset;
          const direct = rowMap.get(column);
          const covering = !direct && mergedRanges.find((range) => rowNumber >= range.start_row && rowNumber <= range.end_row && column >= range.start_column && column <= range.end_column);
          const anchor = covering ? byRow.get(covering.start_row)?.get(covering.start_column) : null;
          const source = direct ?? anchor ?? { text: "", _synthetic: true, _row: rowNumber, _column: column };
          const cell = state.makeCell(covering ? { ...source, text: "", merged_from: { address: source.coordinate ?? source._address ?? `${colLetters(covering.start_column)}${covering.start_row}` } } : source, { tableId, rowIndex: rowNumber, column: offset, rowId: `${sheetName}-r${rowNumber}`, sheetName, cellAddress: source.coordinate ?? source._address });
          if (covering) cell.text = "";
          return cell;
        });
        if (!cellsInRow.some((cell) => clean(cell.text))) continue;
        rows.push({ row_id: `${slug(sheetName)}-r${String(rowNumber).padStart(4, "0")}`, page_no: null, sheet_name: sheetName, cells: cellsInRow });
      }
      result.push({
        id: tableId, caption: sheetName, role: inferRole(sheetName, headersText, rows),
        headers: headersText, header_cells: headerCells, rows, page_no: null, page_numbers: [], sheet_name: sheetName,
        provenance: null, merged_ranges: sheet?.merged ?? [], source_type: "native_xlsx_parts", source_ref: null,
      });
    }
  }
  return result;
}

function nativePartsTables(parsed, state) {
  const parts = Array.isArray(parsed.parts) ? parsed.parts : [];
  const result = [];
  const addTable = (part, index, id, inherited = {}) => {
    const stablePartId = part.id ?? `${part.kind}-${part.index ?? part.page ?? part.slide ?? index + 1}`;
    const tableId = id ?? part.table_id ?? stablePartId;
    result.push(normalizeExplicitTable({
      ...part,
      ...inherited,
      id: tableId,
      caption: part.caption ?? part.title ?? part.text ?? part.name ?? `${part.kind} ${index + 1}`,
      page_no: part.page_no ?? part.page ?? part.slide ?? null,
    }, index, state, "native_parts"));
    for (const [cellIndex, cell] of (part.cells ?? []).entries()) {
      for (const [nestedIndex, nested] of (cell?.nested_tables ?? []).entries()) {
        if (!nested || typeof nested !== "object") continue;
        addTable(nested, cellIndex + nestedIndex, `${tableId}-nested-${cellIndex + 1}-${nestedIndex + 1}`, { parent_table_id: tableId, parent_cell: { row: cell.row ?? null, column: cell.column ?? null } });
      }
    }
  };
  for (const [index, part] of parts.entries()) {
    if (part && (part.kind === "table" || part.kind === "shape" && (Array.isArray(part.rows) || Array.isArray(part.values)))) addTable(part, index);
  }
  return result;
}

function visualTables(parsed, state) {
  const parts = parsed.visual_layout?.parts ?? parsed.layout_json?.parts ?? [];
  const groups = new Map();
  for (const [index, part] of parts.entries()) {
    if (part?.kind !== "table" && !Array.isArray(part?.rows)) continue;
    const key = String(part.table_id ?? part.id ?? `visual-table-${index + 1}`);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ ...part, _adapter_index: index });
  }
  return [...groups.entries()].map(([tableId, fragments], index) => {
    const first = fragments[0];
    const headers = Array.isArray(first.headers) ? first.headers.map((h) => typeof h === "object" ? partText(h) : asString(h)) : (first.rows?.[0] ?? []).map((cell) => typeof cell === "object" ? partText(cell) : asString(cell));
    const headerCells = headers.map((header, column) => {
      const source = first.header_cells?.[column] ?? first.cells?.find((cell) => Number(cell.row) === 0 && Number(cell.column) === column) ?? { text: header };
      const sourceObject = typeof source === "object" && source !== null ? source : { text: asString(source) };
      const headerPath = Array.isArray(first.headers) ? `headers/${column}` : `rows/0/${column}`;
      const sourceWithRef = sourceReference(sourceObject) ? sourceObject : { ...sourceObject, source_ref: `#/visual_layout/parts/${first._adapter_index}/${headerPath}` };
      return state.makeCell(sourceWithRef, { tableId, rowIndex: 0, column, fallback: first, pageNo: firstProvenance(first)?.page_no });
    });
    const rows = [];
    for (const [fragmentIndex, part] of fragments.entries()) {
      const sourceRows = Array.isArray(part.rows) ? part.rows : Array.isArray(part.values) ? part.values : [];
      const hasHeader = sourceRows.length && sourceRows[0].every((cell, col) => clean(typeof cell === "object" ? partText(cell) : cell) === clean(headers[col]));
      for (const [rowIndex, sourceRow] of sourceRows.entries()) {
        if (hasHeader && rowIndex === 0) continue;
        const rowId = `${tableId}-p${firstProvenance(part)?.page_no ?? fragmentIndex + 1}-r${rowIndex + 1}`;
        const cells = rowValues(sourceRow).map((source, column) => {
          const tableCell = part.cells?.find((cell) => Number(cell.row) === rowIndex && Number(cell.column) === column);
          const value = typeof source === "object" ? source : { text: source };
          const rowPath = Array.isArray(sourceRow) ? `rows/${rowIndex}/${column}` : `rows/${rowIndex}/values/${column}`;
          const valueWithRef = sourceReference(value) ? value : { ...value, source_ref: `#/visual_layout/parts/${part._adapter_index}/${rowPath}` };
          return state.makeCell({ ...valueWithRef, ...(tableCell ?? {}) }, { tableId, rowId, rowIndex, column, fallback: part, pageNo: firstProvenance(part)?.page_no });
        });
        if (cells.some((cell) => clean(cell.text))) rows.push({ row_id: rowId, page_no: firstProvenance(part)?.page_no ?? null, sheet_name: part.sheet_name ?? null, cells });
      }
    }
    const pageNumbers = [...new Set(fragments.map((part) => Number(firstProvenance(part)?.page_no ?? part.page_no)).filter(Number.isFinite))];
    return { id: tableId, caption: String(first.text ?? first.caption ?? `Таблица ${index + 1}`), role: first.role ?? inferRole(first.caption ?? first.text, headers, rows), headers, header_cells: headerCells, rows, page_no: pageNumbers.length === 1 ? pageNumbers[0] : null, page_numbers: pageNumbers, sheet_name: first.sheet_name ?? null, provenance: first.provenance ?? null, merged_ranges: first.merged ?? [], source_type: "visual_layout", source_ref: first.ref ?? null };
  });
}

function addFreeElements(parsed, state) {
  const layout = parsed.visual_layout ?? parsed.layout ?? {};
  const sources = [];
  const append = (items, jsonPath, predicate = () => true) => {
    if (!Array.isArray(items)) return;
    for (const [index, source] of items.entries()) if (predicate(source)) sources.push({ source, sourceRef: `#/${jsonPath}/${index}` });
  };
  append(parsed.parts, "parts", (part) => part?.kind !== "sheet" && part?.kind !== "cell" && part?.kind !== "table");
  append(parsed.model_parts, "model_parts", (part) => part?.kind !== "table");
  append(parsed.document?.texts, "document/texts");
  append(parsed.fragments, "fragments");
  append(parsed.values, "values");
  append(layout.parts, "visual_layout/parts", (part) => part?.kind !== "table" && !Array.isArray(part?.rows));
  const seen = new Set();
  for (const [index, item] of sources.entries()) {
    const source = item.source;
    if (source == null) continue;
    const object = typeof source === "object" ? source : { text: asString(source) };
    const text = partText(object);
    const ref = sourceReference(object) ?? object.id ?? item.sourceRef ?? index;
    if (!clean(text) && object.kind !== "value") continue;
    const key = `${ref}|${text}`;
    if (seen.has(key)) continue;
    seen.add(key);
    state.addElement(sourceReference(object) ? object : { ...object, source_ref: item.sourceRef }, { kind: object.kind ?? "text", text, sourceId: ref, sourceType: object.source ?? object.kind ?? "text" });
  }
  if (parsed.values && !Array.isArray(parsed.values) && typeof parsed.values === "object") {
    for (const [key, value] of Object.entries(parsed.values)) {
      if (value == null) continue;
      const object = value && typeof value === "object" ? value : { value };
      const text = partText(object) || (typeof value === "object" ? "" : asString(value));
      if (!clean(text)) continue;
      const ref = sourceReference(object) ?? object.id ?? `#/values/${key}`;
      state.addElement({ ...object, id: object.id ?? `values-${key}` }, { kind: "value", text, sourceId: ref, sourceType: "values" });
    }
  }
}

export function adaptDocumentParserResult(input) {
  const parsed = unwrap(input);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new TypeError("Ожидался JSON результата Document Parser");
  const documentId = documentIdOf(parsed);
  const state = {
    parsed, documentId, elements: [], elementById: new Map(),
    makeProvenance(source, detail) { return makeProvenance(source, { ...detail, parsed, documentId }); },
    addElement(source, detail = {}) {
      const text = detail.text ?? partText(source);
      const explicit = source?.id ?? source?.source_part_id ?? sourceReference(source) ?? detail.sourceId;
      const address = source?.coordinate ?? source?.address ?? detail.cellAddress ?? "";
      const ref = source?.ref ?? source?.self_ref ?? source?.source_ref ?? "";
      const seed = explicit ?? `${detail.kind ?? source?.kind ?? "part"}|${detail.sourceType ?? ""}|${detail.tableId ?? ""}|${detail.rowId ?? detail.rowIndex ?? ""}|${detail.column ?? ""}|${address}|${ref}|${text}|${firstProvenance(source)?.page_no ?? source?.page ?? ""}`;
      const id = `${documentId}:src:${hashId(seed)}`;
      if (state.elementById.has(id)) return state.elementById.get(id);
      const element = {
        id, kind: detail.kind ?? source?.kind ?? "text", text: asString(text),
        source_available: source?.source_available !== false && source?._synthetic !== true && detail.source_available !== false,
        ...(source?.value !== undefined ? { raw_value: source.value } : {}),
        ...(source?.display_value !== undefined ? { display_value: source.display_value } : {}),
        ...(source?.formula ? { formula: source.formula } : {}),
        ...(source?.calculation_status ? { calculation_status: source.calculation_status } : {}),
        ...(detail.sourceType ? { source_type: String(detail.sourceType) } : {}),
        ...(source?.ref ?? source?.self_ref ?? source?.source_ref ? { source_ref: String(source.ref ?? source.self_ref ?? source.source_ref) } : {}),
        provenance: null,
      };
      element.provenance = state.makeProvenance(source, { elementId: id, text: element.text, pageNo: detail.pageNo, sheetName: detail.sheetName, cellAddress: detail.cellAddress, tableId: detail.tableId, rowId: detail.rowId, column: detail.column });
      state.elementById.set(id, element);
      state.elements.push(element);
      return element;
    },
    makeCell(source, detail = {}) {
      const raw = source && typeof source === "object" ? source : { text: asString(source) };
      const text = partText(raw);
      const element = state.addElement(raw, { ...detail, kind: "cell", text, sourceType: raw.kind ?? detail.sourceType ?? "table_cell" });
      const col = Number(detail.column ?? raw.column ?? 0);
      const row = Number(detail.rowIndex ?? raw.row ?? 0);
      const address = raw.address ?? raw.coordinate ?? raw.cell_address ?? detail.cellAddress ?? null;
      const provenance = element.provenance ?? state.makeProvenance(raw, { elementId: element.id, text, ...detail, cellAddress: address });
      return {
        id: element.id, row, column: col, text,
        source_available: element.source_available,
        ...(raw.value !== undefined ? { value: raw.value } : {}),
        ...(raw.display_value !== undefined ? { display_value: raw.display_value } : {}),
        ...(raw.formula ? { formula: raw.formula } : {}),
        ...(raw.calculation_status ? { calculation_status: raw.calculation_status } : {}),
        ...(address ? { address: String(address) } : {}),
        ...(raw.row_span ? { row_span: Number(raw.row_span) } : {}),
        ...(raw.col_span ? { col_span: Number(raw.col_span) } : {}),
        ...(raw.merged_from ? { merged_from: raw.merged_from } : {}),
        page_no: provenance?.page_no ?? detail.pageNo ?? null,
        sheet_name: provenance?.sheet_name ?? detail.sheetName ?? null,
        bbox: provenance?.bbox ?? raw.bbox ?? null,
        provenance,
      };
    },
  };

  const layout = parsed.visual_layout ?? input?.layout_json ?? input?.layout ?? null;
  const pages = layout?.pages ?? parsed.document?.pages ?? {};
  const pageCount = Number(parsed.page_count ?? Object.keys(pages).length ?? 0) || null;
  addFreeElements(parsed, state);

  let tables = normalizeEnvelopeTables(parsed, state);
  if (!tables.length && /xlsx|xlsm|spreadsheet/i.test(String(parsed.source_extension ?? parsed.format ?? ""))) tables = officeTables(parsed, state);
  if (!tables.length) tables = nativePartsTables(parsed, state);
  if (!tables.length && Array.isArray(parsed.document?.tables) && parsed.document.tables.length) tables = parsed.document.tables.map((table, index) => normalizeDoclingTable(table, index, state, "document.tables"));
  if (!tables.length && Array.isArray(parsed.model_parts)) {
    tables = parsed.model_parts.filter((part) => part?.kind === "table" && part.data).map((table, index) => normalizeDoclingTable(table, index, state, "model_parts"));
  }
  if (!tables.length) tables = visualTables(parsed, state);
  if (!tables.length) tables = officeTables(parsed, state);

  const metadata = parsed.document?.origin ?? {};
  const extensionValue = parsed.source_extension ?? parsed.format;
  const sourceExtension = extensionValue ? String(extensionValue).startsWith(".") ? String(extensionValue) : `.${extensionValue}` : "";
  const documentName = parsed.document?.name == null ? "" : String(parsed.document.name);
  const documentFileName = documentName && sourceExtension && !documentName.toLocaleLowerCase("ru-RU").endsWith(sourceExtension.toLocaleLowerCase("ru-RU")) ? `${documentName}${sourceExtension}` : documentName;
  const fileName = String(parsed.file_name ?? parsed.filename ?? metadata.filename ?? (documentFileName || parsed.title) ?? `${documentId}.json`);
  const format = String(parsed.format ?? parsed.source_extension ?? fileName.split(".").pop() ?? "JSON").replace(/^\./, "").toUpperCase();
  const sheetNames = [...new Set([
    ...(Array.isArray(parsed.workbook?.sheet_names) ? parsed.workbook.sheet_names : []),
    ...(Array.isArray(parsed.parts) ? parsed.parts.filter((part) => part?.kind === "sheet").map((part) => part.name) : []),
    ...tables.map((table) => table.sheet_name).filter(Boolean),
  ].map(String))];
  const pageNumbers = state.elements.map((element) => element.provenance?.page_no).filter(Number.isFinite);
  const maxPage = pageNumbers.length ? Math.max(...pageNumbers) : 0;
  return {
    adapter_version: "document-parser-unified/1.1.0",
    document_id: documentId,
    title: String(parsed.title ?? metadata.filename ?? fileName),
    file_name: fileName,
    format,
    page_count: pageCount ?? maxPage ?? null,
    page_sizes: pages,
    sheet_names: sheetNames,
    elements: state.elements,
    tables,
    parser_sections: {
      parts: Array.isArray(parsed.parts) ? parsed.parts.length : 0,
      model_parts: Array.isArray(parsed.model_parts) ? parsed.model_parts.length : 0,
      visual_layout_parts: Array.isArray(layout?.parts) ? layout.parts.length : 0,
      logical_tables: Array.isArray(parsed.logical_tables) ? parsed.logical_tables.length : 0,
    },
  };
}

export function parserInputShapeErrors(value) {
  const parsed = unwrap(value);
  const errors = [];
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return ["Ожидался JSON-объект результата Document Parser"];
  const hasContent = [parsed.parts, parsed.model_parts, parsed.document?.texts, parsed.fragments, parsed.values, parsed.logical_tables, parsed.document?.tables, parsed.visual_layout?.parts]
    .some((items) => Array.isArray(items) && items.length > 0)
    || [parsed.text, parsed.markdown, parsed.document?.text, parsed.document?.markdown].some((text) => typeof text === "string" && text.trim().length > 0);
  if (!hasContent) errors.push("Нет распознанного текста или структурированных данных парсера");
  return errors;
}

