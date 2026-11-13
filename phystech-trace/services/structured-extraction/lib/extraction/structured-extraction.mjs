import { schemaRegistry, validateExtraction } from "./schema-registry.mjs";
import { adaptDocumentParserResult, parserInputShapeErrors } from "../parser/document-parser-adapter.mjs";

const adaptedCache = new WeakMap();
function adapted(parsed) {
  if (!parsed || typeof parsed !== "object") return adaptDocumentParserResult(parsed);
  if (!adaptedCache.has(parsed)) adaptedCache.set(parsed, adaptDocumentParserResult(parsed));
  return adaptedCache.get(parsed);
}

const monthMap = {
  январь: "01", января: "01", февраль: "02", февраля: "02", март: "03", марта: "03",
  апрель: "04", апреля: "04", май: "05", мая: "05", июнь: "06", июня: "06",
  июль: "07", июля: "07", август: "08", августа: "08", сентябрь: "09", сентября: "09",
  октябрь: "10", октября: "10", ноябрь: "11", ноября: "11", декабрь: "12", декабря: "12",
};

const fieldsByType = {
  kfz_report: [
    ["report_number", "Номер отчёта", ["номер отчёта", "регистрационный номер", "номер формы"], "identifier"],
    ["report_date", "Дата составления", ["дата составления", "дата отчёта", "дата документа"], "date"],
    ["reporting_period", "Отчётный период", ["отчётный период", "отчетный период", "период"], "date_range"],
    ["reporting_organization", "Отчитывающаяся организация", ["отчитывающаяся организация", "исполнитель", "организация"], "text"],
    ["customer", "Заказчик", ["заказчик"], "text"],
    ["supplier_inn", "ИНН исполнителя", ["инн исполнителя", "инн поставщика"], "inn"],
    ["customer_inn", "ИНН заказчика", ["инн заказчика"], "inn"],
    ["contract_reference", "Договор", ["договор", "основание"], "identifier"],
    ["currency", "Валюта отчёта", ["валюта отчёта", "валюта"], "currency"],
    ["reported_total", "Общая сумма по отчёту", ["общая сумма по отчёту", "итого по отчёту", "итого"], "money"],
    ["responsible", "Ответственный", ["ответственный", "составитель"], "text"],
    ["customer_signatory", "Подписант заказчика", ["подписант заказчика", "представитель заказчика"], "text"],
  ],
  contract: [
    ["contract_number", "Номер договора", ["номер договора", "договор"], "identifier"],
    ["contract_date", "Дата договора", ["дата договора", "дата подписания"], "date"],
    ["contractor", "Подрядчик", ["подрядчик", "исполнитель"], "text"],
    ["contractor_inn", "ИНН подрядчика", ["инн подрядчика", "инн исполнителя"], "inn"],
    ["customer", "Заказчик", ["заказчик"], "text"],
    ["customer_inn", "ИНН заказчика", ["инн заказчика"], "inn"],
    ["contract_amount", "Цена договора", ["цена договора", "сумма договора"], "money"],
    ["vat_rate", "Ставка НДС", ["ставка ндс", "ндс"], "percentage"],
    ["contract_term", "Срок выполнения", ["срок выполнения", "срок действия"], "date_range"],
    ["object_address", "Адрес объекта", ["адрес объекта", "место выполнения"], "text"],
    ["payment_terms", "Условия оплаты", ["условия оплаты", "порядок оплаты"], "text"],
    ["bank_account", "Расчётный счёт подрядчика", ["расчётный счёт подрядчика", "расчетный счет", "р/с"], "bank_account"],
    ["bank_bik", "БИК банка", ["бик банка", "бик"], "bank_bik"],
  ],
  act: [
    ["act_number", "Номер акта", ["номер акта", "номер документа"], "identifier"],
    ["act_date", "Дата акта", ["дата акта", "дата"], "date"],
    ["contract_reference", "Договор", ["договор", "основание"], "identifier"],
    ["execution_period", "Период выполнения", ["период выполнения", "отчётный период", "период"], "date_range"],
    ["contractor", "Исполнитель", ["исполнитель", "подрядчик"], "text"],
    ["customer", "Заказчик", ["заказчик"], "text"],
    ["amount_due", "Итого к оплате", ["итого к оплате", "всего к оплате", "итого"], "money"],
    ["vat_amount", "НДС", ["ндс", "в том числе ндс"], "money"],
    ["contractor_representative", "Представитель исполнителя", ["представитель исполнителя", "представитель подрядчика"], "text"],
    ["customer_representative", "Представитель заказчика", ["представитель заказчика", "подписант заказчика"], "text"],
    ["customer_remarks", "Замечания заказчика", ["замечания заказчика", "замечания"], "text"],
  ],
  invoice: [
    ["invoice_number", "Номер счёта", ["номер счёта", "номер счета"], "identifier"],
    ["invoice_date", "Дата счёта", ["дата счёта", "дата счета", "дата"], "date"],
    ["supplier", "Поставщик", ["поставщик", "исполнитель"], "text"],
    ["supplier_inn", "ИНН поставщика", ["инн поставщика"], "inn"],
    ["buyer", "Покупатель", ["покупатель", "заказчик"], "text"],
    ["buyer_inn", "ИНН покупателя", ["инн покупателя", "инн заказчика"], "inn"],
    ["contract_reference", "Основание", ["основание", "договор"], "identifier"],
    ["payment_deadline", "Срок оплаты", ["срок оплаты", "оплатить до"], "date"],
    ["total_amount", "Итого с НДС", ["итого с ндс", "сумма счёта", "сумма счета"], "money"],
    ["vat_amount", "В том числе НДС", ["в том числе ндс", "ндс"], "money"],
    ["payee_bank", "Банк получателя", ["банк получателя", "банк"], "text"],
    ["correspondent_account", "Корреспондентский счёт", ["корреспондентский счёт", "корреспондентский счет"], "bank_account"],
  ],
  addendum: [
    ["addendum_number", "Номер соглашения", ["номер соглашения", "дополнительное соглашение", "номер"], "identifier"],
    ["signing_date", "Дата подписания", ["дата подписания", "дата"], "date"],
    ["base_contract", "Основной договор", ["основной договор", "договор"], "identifier"],
    ["party_1", "Сторона 1", ["сторона 1", "подрядчик", "исполнитель"], "text"],
    ["party_2", "Сторона 2", ["сторона 2", "заказчик"], "text"],
    ["previous_amount", "Цена до изменения", ["цена до изменения", "прежняя цена", "цена договора"], "money"],
    ["new_amount", "Цена после изменения", ["цена после изменения", "новая цена"], "money"],
    ["effective_date", "Дата вступления в силу", ["дата вступления в силу", "вступает в силу"], "date"],
    ["change_reason", "Причина изменения", ["причина изменения", "основание изменения"], "text"],
  ],
  registry: [
    ["registry_name", "Наименование реестра", ["наименование реестра", "реестр"], "text"],
    ["reporting_period", "Период", ["период", "отчётный период"], "date_range"],
    ["organization", "Организация", ["организация", "исполнитель"], "text"],
    ["counterparty", "Контрагент", ["контрагент", "заказчик", "покупатель"], "text"],
    ["contract_reference", "Договор", ["договор", "основание"], "identifier"],
    ["registry_total", "Итого по реестру", ["итого по реестру", "итого", "общая сумма"], "money"],
    ["registry_status", "Статус", ["статус"], "text"],
  ],
  unknown: [],
};

export const fieldDefinitions = fieldsByType;

function clean(value) {
  return String(value ?? "").replace(/\u00a0|\u202f/g, " ").trim();
}

function canonical(value) {
  return clean(value).toLocaleLowerCase("ru-RU").replace(/ё/g, "е").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

function provenanceOf(cell, documentId) {
  let input = Array.isArray(cell?.provenance) ? cell.provenance[0] : cell?.provenance;
  if (!input && (cell?.bbox || cell?.address || cell?.cell_address)) input = {
    document_id: documentId, source_part_id: cell?.id, source_ref: cell?.source_ref,
    page_no: cell?.page_no ?? null, sheet_name: cell?.sheet_name ?? null,
    cell_address: cell?.cell_address ?? cell?.address ?? null, bbox: cell?.bbox ?? null,
    coordinate_origin: cell?.bbox?.coord_origin ?? null, table_id: cell?.table_id,
    row_id: cell?.row_id, column_index: cell?.column, source_text: cell?.text ?? cell?.value ?? "",
    confidence: cell?.confidence ?? null,
  };
  if (!input) return null;
  const sourceText = String(input.source_text ?? cell?.text ?? cell?.value ?? "");
  const confidence = input.confidence ?? cell?.confidence;
  return {
    document_id: String(input.document_id ?? documentId),
    source_part_id: input.source_part_id ?? cell?.id,
    source_ref: input.source_ref,
    page_no: input.page_no ?? null,
    sheet_name: input.sheet_name ?? null,
    cell_address: input.cell_address ?? cell?.address ?? null,
    bbox: input.bbox ?? cell?.bbox ?? null,
    coordinate_origin: input.coordinate_origin ?? input.bbox?.coord_origin ?? null,
    page_size: input.page_size ?? null,
    table_id: input.table_id ?? cell?.table_id,
    row_id: input.row_id ?? cell?.row_id,
    column_index: input.column_index ?? cell?.column,
    source_text: sourceText,
    confidence: confidence != null && Number.isFinite(Number(confidence)) ? Number(confidence) : null,
    source_available: input.source_available !== false && cell?.source_available !== false,
    ...(input.provenance_alternates ? { provenance_alternates: input.provenance_alternates } : {}),
  };
}

function allText(parsed) {
  const source = adapted(parsed);
  const strings = source.elements.filter((item) => item.source_available !== false).map((item) => item.text);
  for (const table of source.tables) {
    strings.push(...(table.header_cells ?? []).filter((cell) => cell.source_available !== false).map((cell) => cell.text ?? ""));
    for (const row of table.rows ?? []) strings.push(...(row.cells ?? []).filter((cell) => cell.source_available !== false).map((cell) => cell.text ?? cell.value ?? ""));
  }
  strings.push(source.title, source.file_name);
  if (typeof parsed.markdown === "string") strings.push(parsed.markdown);
  return strings.join(" \n ").toLocaleLowerCase("ru-RU").replace(/ё/g, "е");
}

export function classifyDocument(parsed, llmClassification = null) {
  const text = allText(parsed);
  const rules = [
    ["addendum", /дополнительн.{0,20}соглаш|(?:^|[^а-яёa-z])дс\s*[-№]?\s*\d|\baddendum\b|\bsupplementary agreement\b/i, "Дополнительное соглашение", 0.97],
    ["kfz_report", /(?:кфз|контрольно[- ]финансов.{0,20}отчет|отчет.{0,20}кфз)/i, "Отчёт КФЗ", 0.98],
    ["invoice", /счет\s+на\s+оплат|счет-фактур|номер\s+счета|\binvoice\b|\binv\s*[№#-]/i, "Счёт", 0.95],
    ["act", /акт\s+(?:сдачи|приемки|приёмки|выполненных|оказанных)|номер\s+акта|\bakt\s*(?:n|№|#|-)|\bact\s+(?:of|n|№|-)/i, "Акт", 0.95],
    ["contract", /договор\s+(?:подряда|оказания|поставки|обслуживания)|номер\s+договора|\bcontract\s*(?:n|№|#|-)/i, "Договор", 0.94],
    ["registry", /реестр\s+(?:выполненных|работ|поставок|операций)|наименование\s+реестра|\bregister\s+of\b/i, "Реестр", 0.92],
  ];
  let ruleGuess = null;
  for (const [type, pattern, label, confidence] of rules) {
    if (pattern.test(text)) { ruleGuess = { type, label, confidence }; break; }
  }
  const llmType = llmClassification?.document_type && schemaRegistry[llmClassification.document_type] ? llmClassification.document_type : null;
  if (ruleGuess && llmType && ruleGuess.type !== llmType) return {
    ...ruleGuess, status: "review", method: "conflict",
    conflict: { rules_type: ruleGuess.type, llm_type: llmType, reason: "Детерминированные признаки и LLM классифицировали документ по-разному" },
  };
  if (ruleGuess && llmType) return { ...ruleGuess, status: "classified", method: "consensus", llm_type: llmType };
  if (ruleGuess) return { ...ruleGuess, status: ruleGuess.confidence >= 0.9 ? "classified" : "review", method: "rules" };
  if (llmType) {
    const confidence = typeof llmClassification.confidence === "number"
      && Number.isFinite(llmClassification.confidence)
      && llmClassification.confidence >= 0
      && llmClassification.confidence <= 1
      ? llmClassification.confidence
      : null;
    return { type: llmType, label: schemaRegistry[llmType].label, confidence, status: "review", method: "llm_only", note: "Нет достаточных детерминированных признаков; классификация требует проверки" };
  }
  return { type: "unknown", label: "Тип не определён", confidence: 0.42, status: "review" };
}

function parseDecimalString(raw) {
  let value = clean(raw).replace(/[\s\u00a0\u202f'’]/g, "");
  if (!value || /\?|\/|\bили\b/i.test(value)) return null;
  let negative = false;
  if (/^\(.*\)$/.test(value)) { negative = true; value = value.slice(1, -1); }
  value = value.replace(/[^\d,.-]/g, "");
  if (!/\d/.test(value) || (value.match(/-/g) ?? []).length > (value.startsWith("-") ? 1 : 0)) return null;
  if (value.startsWith("-")) { negative = true; value = value.slice(1); }
  if (value.includes("-") || !value) return null;
  const commaCount = (value.match(/,/g) ?? []).length;
  const dotCount = (value.match(/\./g) ?? []).length;
  let decimalSeparator = null;
  if (commaCount && dotCount) {
    decimalSeparator = value.lastIndexOf(",") > value.lastIndexOf(".") ? "," : ".";
    const groupSeparator = decimalSeparator === "," ? "." : ",";
    const [integerPart] = value.split(decimalSeparator);
    const grouped = integerPart.split(groupSeparator);
    if (grouped.length > 1 && (!/^\d{1,3}$/.test(grouped[0]) || grouped.slice(1).some((part) => !/^\d{3}$/.test(part)))) return null;
    if ((value.split(decimalSeparator).length !== 2) || !/^\d{1,6}$/.test(value.split(decimalSeparator)[1])) return null;
  } else if (commaCount || dotCount) {
    const separator = commaCount ? "," : ".";
    const chunks = value.split(separator);
    if (chunks.some((chunk) => !/^\d+$/.test(chunk))) return null;
    if (chunks.length > 2) {
      if (!/^\d{1,3}$/.test(chunks[0]) || chunks.slice(1).some((part) => !/^\d{3}$/.test(part))) return null;
      value = chunks.join("");
    } else if (chunks[1].length === 3) {
      return null; // A single three-digit suffix may be decimal or thousands grouping.
    } else if (chunks[1].length >= 1 && chunks[1].length <= 6) {
      decimalSeparator = separator;
    } else return null;
  }
  const decimalAt = decimalSeparator ? value.lastIndexOf(decimalSeparator) : -1;
  let integerPart = decimalAt >= 0 ? value.slice(0, decimalAt) : value;
  let fraction = decimalAt >= 0 ? value.slice(decimalAt + 1) : "";
  integerPart = integerPart.replace(/[.,]/g, "");
  fraction = fraction.replace(/[.,]/g, "");
  if (!/^\d+$/.test(integerPart) || (fraction && !/^\d+$/.test(fraction))) return null;
  integerPart = integerPart.replace(/^0+(?=\d)/, "") || "0";
  return `${negative ? "-" : ""}${integerPart}${fraction ? `.${fraction}` : ""}`;
}

function firstNumericToken(raw) {
  const value = clean(raw);
  const match = value.match(/[+-]?\d[\d\s\u00a0\u202f.,?]*(?:\d|\?)/);
  return match?.[0]?.trim() ?? "";
}

function dateResult(raw) {
  const value = clean(raw);
  if (!value) return { value: null, status: "missing", note: null };
  const validDate = (year, month, day) => {
    const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
    return date.getUTCFullYear() === Number(year) && date.getUTCMonth() === Number(month) - 1 && date.getUTCDate() === Number(day);
  };
  const outputDate = (year, month, day) => {
    if (!validDate(year, month, day)) return { value: null, status: "review", note: "Дата выходит за допустимые границы календаря" };
    return { value: `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`, status: "extracted", note: null };
  };
  const iso = value.match(/\b(20\d{2})-(\d{1,2})-(\d{1,2})\b/);
  if (iso) return outputDate(iso[1], iso[2], iso[3]);
  const words = value.toLocaleLowerCase("ru-RU").match(/\b(\d{1,2})\s+([а-яё]+)\s+(20\d{2})\b/);
  if (words && monthMap[words[2]]) return outputDate(words[3], monthMap[words[2]], words[1]);
  const numeric = value.match(/\b(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})\b/);
  if (!numeric) return { value: null, status: "review", note: "Дата не распознана однозначно" };
  const [, first, separator, second, rawYear] = numeric;
  if (rawYear.length === 2) return { value: null, status: "review", note: "Двузначный год неоднозначен" };
  const year = rawYear;
  let day = Number(first);
  let month = Number(second);
  if (day <= 12 && month <= 12 && separator !== ".") return { value: null, status: "review", note: "Порядок дня и месяца неоднозначен" };
  if (day > 12 && month <= 12) { day = Number(first); month = Number(second); }
  else if (month > 12 && day <= 12) { day = Number(second); month = Number(first); }
  else if (day > 12 && month > 12) return { value: null, status: "review", note: "Месяц выходит за допустимые границы" };
  return outputDate(year, month, day);
}

function validateInn(value) {
  const digits = value.replace(/\D/g, "");
  const checksum = (sequence, weights) => weights.reduce((sum, weight, index) => sum + Number(sequence[index]) * weight, 0) % 11 % 10;
  if (digits.length === 10) return checksum(digits, [2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(digits[9]);
  if (digits.length === 12) return checksum(digits, [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === Number(digits[10])
    && checksum(digits, [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8, 0]) === Number(digits[11]);
  return false;
}

function detectCurrency(value, hint = null) {
  const text = `${value} ${hint ?? ""}`.toLocaleLowerCase("ru-RU");
  if (/(?:^|[^\p{L}])(?:rub|руб(?:\.|лей|ля|ль)?|российск.{0,8}руб)(?:$|[^\p{L}])|₽/u.test(text)) return "RUB";
  if (/(?:^|[^\p{L}])(?:eur|евро)(?:$|[^\p{L}])|€/u.test(text)) return "EUR";
  if (/(?:^|[^\p{L}])(?:usd|доллар.{0,8}(?:сша|американ))(?:$|[^\p{L}])|\$/u.test(text)) return "USD";
  if (/(?:^|[^\p{L}])(?:cny|юан.{0,4})(?:$|[^\p{L}])|元/u.test(text)) return "CNY";
  return null;
}

function normalize(raw, kind, options = {}) {
  const value = clean(raw);
  if (!value) return { value: null, status: "missing", note: null };
  if (kind === "date") return dateResult(value);
  if (kind === "date_range") {
    const tokens = value.match(/(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s+[а-яё]+\s+\d{4})/giu) ?? [];
    if (tokens.length !== 2) return { value: null, status: "review", note: "Период указан без двух однозначных границ" };
    const start = dateResult(tokens[0]);
    const end = dateResult(tokens[1]);
    if (start.status !== "extracted" || end.status !== "extracted") return { value: null, status: "review", note: "Одна или обе границы периода требуют проверки" };
    if (start.value > end.value) return { value: null, status: "review", note: "Начало периода позже окончания" };
    return { value: { start: start.value, end: end.value }, status: "extracted", note: null };
  }
  if (kind === "money") {
    if (value.includes("?") || /\d\s*\/\s*\d/.test(value)) return { value: null, status: "review", note: "Сумма распознана неоднозначно" };
    const numeric = firstNumericToken(value);
    const decimal = parseDecimalString(numeric);
    if (decimal === null) return { value: null, status: "review", note: "Не удалось безопасно нормализовать сумму" };
    const currency = detectCurrency(value, options.currencyHint);
    return { value: { amount: decimal, currency }, status: currency ? "extracted" : "review", note: currency ? null : "Валюта не указана в значении или заголовке источника" };
  }
  if (kind === "percentage") {
    const decimal = parseDecimalString(firstNumericToken(value));
    return decimal === null ? { value: null, status: "review", note: "Процент требует проверки" } : { value: decimal, status: "extracted", note: null };
  }
  if (kind === "quantity") {
    const decimal = parseDecimalString(value);
    return decimal === null ? { value: null, status: "review", note: "Количество распознано неоднозначно" } : { value: decimal, status: "extracted", note: null };
  }
  if (kind === "unit") {
    const key = value.toLocaleLowerCase("ru-RU").replace(/ё/g, "е").replace(/\s/g, "");
    const map = { "шт.": "piece", шт: "piece", штука: "piece", штуки: "piece", "компл.": "set", компл: "set", комплект: "set", "чел.-ч": "person_hour", "чел-ч": "person_hour", "чел/ч": "person_hour", "м³": "cubic_meter", "м3": "cubic_meter", м: "meter", "м.п.": "linear_meter", кг: "kilogram", т: "tonne", тонна: "tonne", объект: "object", точка: "point", смена: "shift", рейс: "trip", линия: "line", час: "hour", "кв.м": "square_meter", "м²": "square_meter", "м2": "square_meter", услуга: "service", месяц: "month", день: "day", пара: "pair" };
    return map[key] ? { value: map[key], status: "extracted", note: null } : { value: null, status: "review", note: "Единица отсутствует в справочнике; исходное значение сохранено" };
  }
  if (kind === "inn") {
    const digits = value.replace(/\D/g, "");
    return validateInn(digits) ? { value: digits, status: "extracted", note: null } : { value: digits || null, status: "review", note: "ИНН должен содержать 10 или 12 цифр с корректной контрольной суммой" };
  }
  if (kind === "bank_bik") {
    const digits = value.replace(/\D/g, "");
    const valid = /^0[45]\d{7}$/.test(digits);
    return { value: digits || null, status: valid ? "extracted" : "review", note: valid ? null : "БИК должен содержать 9 цифр и начинаться с 04 или 05" };
  }
  if (kind === "bank_account") {
    const digits = value.replace(/\D/g, "");
    return { value: digits || null, status: digits.length === 20 ? "extracted" : "review", note: digits.length === 20 ? null : "Банковский счёт должен содержать 20 цифр" };
  }
  if (kind === "identifier") return { value: value.normalize("NFC").replace(/\s+/g, " "), status: "extracted", note: null };
  if (kind === "currency") {
    const key = value.toLocaleLowerCase("ru-RU");
    if (/руб|российск|₽/.test(key)) return { value: "RUB", status: "extracted", note: null };
    if (/евро|eur|€/.test(key)) return { value: "EUR", status: "extracted", note: null };
    if (/доллар|usd|\$/.test(key)) return { value: "USD", status: "extracted", note: null };
    return { value: value, status: "review", note: "Код валюты не определён однозначно" };
  }
  return { value, status: "extracted", note: null };
}

function valueObject(parsed, cell, sourceValue, kind, fallbackReason = null, options = {}) {
  const provenance = provenanceOf(cell, parsed.document_id);
  if (!cell) return { value: null, source_value: null, status: "missing", confidence: null, provenance: null, normalization_note: fallbackReason };
  if (!clean(sourceValue)) return { value: null, source_value: null, status: "missing", confidence: provenance?.confidence ?? null, provenance, normalization_note: fallbackReason };
  const sourceText = String(provenance?.source_text ?? "");
  const hasLocator = Boolean(provenance?.source_ref || provenance?.cell_address || (Number.isFinite(provenance?.page_no) && provenance?.bbox) || (provenance?.page_no != null && provenance?.source_part_id));
  const sourceAvailable = cell.source_available !== false && provenance?.source_available !== false;
  if (!provenance || !hasLocator || !sourceAvailable || !sourceText.trim() || !sourceText.includes(String(sourceValue))) {
    return { value: null, source_value: String(sourceValue), status: "review", confidence: provenance?.confidence ?? null, provenance, normalization_note: !provenance || !hasLocator ? "Нет проверяемого локатора исходного значения" : !sourceAvailable ? "Исходный источник недоступен для подтверждения" : !sourceText.trim() || !sourceText.includes(String(sourceValue)) ? "Исходный текст не подтверждает извлечённое значение" : fallbackReason };
  }
  if (provenance.confidence != null && provenance.confidence < 0.8) {
    return { value: null, source_value: String(sourceValue), status: "review", confidence: provenance.confidence, provenance, normalization_note: "Низкая уверенность исходного парсера" };
  }
  if (cell?.calculation_status === "missing_cached_result" || (cell?.formula && cell?.value == null && cell?.cached_value == null)) {
    return { value: null, source_value: String(sourceValue), status: "review", confidence: provenance?.confidence ?? null, provenance, normalization_note: "У формулы отсутствует сохранённый результат; значение не вычислялось" };
  }
  const normalized = normalize(sourceValue, kind, options);
  const confidence = provenance?.confidence ?? (cell.confidence != null && Number.isFinite(Number(cell.confidence)) ? Number(cell.confidence) : null);
  const lowConfidence = confidence != null && confidence < 0.8;
  const status = normalized.status === "missing" ? "missing" : normalized.status === "review" || (confidence != null && lowConfidence) ? "review" : "extracted";
  return {
    value: normalized.value,
    source_value: String(sourceValue),
    status,
    confidence,
    provenance,
    normalization_note: normalized.note ?? (confidence != null && lowConfidence ? "Низкая уверенность исходного парсера" : null),
    ...(options.source_method ? { source_method: options.source_method } : {}),
    ...(options.conflict ? { conflict: options.conflict } : {}),
  };
}

function metadataRows(tables) {
  return tables.filter((table) => table.role === "metadata" || canonical(table.caption).includes("реквизиты документа"));
}

function lookupMetadata(tables, aliases) {
  const aliasSet = aliases.map(canonical);
  let best = null;
  let bestScore = -1;
  for (const table of metadataRows(tables)) {
    for (const row of table.rows ?? []) {
      const cells = [...(row.cells ?? [])].sort((a, b) => (a.column ?? 0) - (b.column ?? 0));
      if (cells.length < 2) continue;
      if (cells[0].source_available === false || cells[1].source_available === false) continue;
      const label = canonical(cells[0].text ?? cells[0].value);
      const matched = aliasSet.map((alias) => ({ alias, score: label === alias ? 1000 + alias.length : alias.length >= 5 && label.includes(alias) ? 100 + alias.length : -1 }))
        .sort((left, right) => right.score - left.score)[0];
      if (matched?.score > bestScore) { bestScore = matched.score; best = { cell: cells[1], text: cells[1].text ?? cells[1].value ?? "", method: "rules" }; }
    }
  }
  return bestScore >= 0 ? best : null;
}

function lookupFreeText(parsed, aliases) {
  const aliasSet = aliases.map(canonical);
  let unavailableCandidate = null;
  for (const element of adapted(parsed).elements) {
    const text = clean(element.text);
    if (!text) continue;
    for (const line of text.split(/\r?\n/)) {
      const delimiter = line.search(/[:：=]/);
      if (delimiter < 1) continue;
      const label = canonical(line.slice(0, delimiter));
      if (!aliasSet.some((alias) => label === alias || alias.length >= 5 && (label.includes(alias) || alias.includes(label) && label.length >= 5))) continue;
      const value = clean(line.slice(delimiter + 1));
      const candidate = { cell: { id: element.id, text: value, source_available: element.source_available, provenance: element.provenance ? { ...element.provenance, source_text: text } : null, confidence: element.provenance?.confidence ?? null }, text: value, method: "rules" };
      if (element.source_available === false) { unavailableCandidate ??= candidate; continue; }
      return candidate;
    }
  }
  return unavailableCandidate;
}

function groundedFieldCandidate(parsed, fieldKey, llm) {
  const candidate = llm?.field_candidates?.find((item) => item.field_key === fieldKey);
  if (!candidate) return null;
  const element = adapted(parsed).elements.find((item) => item.id === candidate.source_element_id);
  const sourceValue = String(candidate.source_value ?? "");
  if (!element || element.source_available === false || !sourceValue || !String(element.text ?? "").includes(sourceValue)) return null;
  const provenance = element.provenance ? { ...element.provenance, source_text: element.text } : null;
  return { cell: { id: element.id, text: sourceValue, provenance, confidence: element.provenance?.confidence ?? null }, text: sourceValue, method: "llm", model_confidence: candidate.confidence ?? null };
}

function normalizedCandidate(parsed, candidate, kind, options = {}) {
  return valueObject(parsed, candidate.cell, candidate.text, kind, null, { ...options, source_method: candidate.method });
}

function equalNormalized(left, right) {
  return JSON.stringify(left.value) === JSON.stringify(right.value) && left.status !== "review" && right.status !== "review";
}

function fieldValue(parsed, tables, [key, label, aliases, kind], llm, mode) {
  const ruleCandidate = lookupMetadata(tables, aliases) ?? lookupFreeText(parsed, aliases);
  const llmCandidate = mode === "rules_only" ? null : groundedFieldCandidate(parsed, key, llm);
  let extracted;
  if (ruleCandidate && llmCandidate) {
    const ruleValue = normalizedCandidate(parsed, ruleCandidate, kind);
    const llmValue = normalizedCandidate(parsed, llmCandidate, kind);
    if (equalNormalized(ruleValue, llmValue)) extracted = { ...ruleValue, source_method: "consensus", corroborated_by: "llm" };
    else extracted = {
      ...ruleValue,
      value: null,
      status: "review",
      source_method: "conflict",
      conflict: {
        reason: "Rules и LLM выбрали разные исходные значения; автоматический выбор небезопасен",
        rules: { source_value: ruleValue.source_value, value: ruleValue.value, provenance: ruleValue.provenance },
        llm: { source_value: llmValue.source_value, value: llmValue.value, provenance: llmValue.provenance },
      },
      normalization_note: "Конфликт кандидатов. Проверьте обе исходные ссылки.",
    };
  } else if (ruleCandidate) extracted = normalizedCandidate(parsed, ruleCandidate, kind);
  else if (llmCandidate) extracted = normalizedCandidate(parsed, llmCandidate, kind);
  else extracted = valueObject(parsed, null, null, kind);
  extracted.label = label;
  return { key, label, extracted };
}

function findHeader(headers, pattern, excluded = null) {
  const normalized = headers.map((header) => canonical(header));
  return normalized.findIndex((header) => pattern.test(header) && !(excluded && excluded.test(header)));
}

function lineItems(parsed, table, options = {}) {
  const headers = table.headers ?? [];
  const mapping = options.llm?.table_mappings?.find((item) => item.table_id === table.id);
  const mapped = new Map();
  const headerRefs = new Set((table.header_cells ?? []).flatMap((cell) => cell.source_available === false ? [] : [cell.id, ...(cell.source_element_ids ?? [])]));
  for (const column of mapping?.columns ?? []) {
    if (!headerRefs.has(column.source_element_id)) continue;
    const index = (table.header_cells ?? []).findIndex((cell) => cell.id === column.source_element_id || cell.source_element_ids?.includes(column.source_element_id));
    if (index >= 0 && !mapped.has(column.semantic_key)) mapped.set(column.semantic_key, index);
  }
  const mappedIndex = (key, fallback) => mapped.has(key) ? mapped.get(key) : fallback;
  const idIndex = mappedIndex("identifier", findHeader(headers, /идентификатор|код|артикул|номер\s*позиции/));
  const lineIndex = mappedIndex("line_number", headers.findIndex((header) => /^\s*№\s*$/.test(header) || /^(номер|этап|строка)$/.test(canonical(header))));
  const descriptionIndex = mappedIndex("description", findHeader(headers, /наимен|описан|содержание|показател|работ/));
  const unitIndex = mappedIndex("unit", findHeader(headers, /единиц|^ед изм$|^ед$/));
  const plannedIndex = mappedIndex("planned_quantity", findHeader(headers, /план|запланир/));
  const actualIndex = mappedIndex("actual_quantity", findHeader(headers, /факт|выполнен|колич|кол\s*во|^объем$/));
  const quantityIndex = mappedIndex("quantity", actualIndex >= 0 ? actualIndex : findHeader(headers, /колич|кол\s*во|объем/));
  const unitPriceIndex = mappedIndex("unit_price", findHeader(headers, /цена|тариф|стоимость\s*(?:за|ед)/, /сумм|итого/));
  const amountIndex = mappedIndex("amount", findHeader(headers, /сумм|стоимость|итого|к\s*оплате/));
  const selectCell = (row, index) => index < 0 ? null : row.cells?.find((cell) => cell.column === index) ?? row.cells?.[index] ?? null;

  return (table.rows ?? []).map((row, rowIndex) => {
    const cellValue = (index, kind) => {
      const cell = selectCell(row, index);
      const header = index >= 0 ? headers[index] ?? "" : "";
      return valueObject(parsed, cell, cell?.text ?? cell?.value ?? null, kind, null, { currencyHint: header });
    };
    const sourceCells = [...(row.cells ?? [])].sort((a, b) => (a.column ?? 0) - (b.column ?? 0)).map((cell) => ({
      column: Number(cell.column ?? 0),
      header: String(headers[cell.column] ?? cell.column_name ?? `Колонка ${Number(cell.column ?? 0) + 1}`),
      extracted: valueObject(parsed, cell, cell.text ?? cell.value ?? null, inferHeaderKind(headers[cell.column] ?? ""), null, { currencyHint: headers[cell.column] ?? "" }),
    }));
    const canonicalId = idIndex >= 0 ? cellValue(idIndex, "identifier") : lineIndex >= 0 ? cellValue(lineIndex, "identifier") : valueObject(parsed, null, null, "identifier");
    const rowStatus = sourceCells.some((entry) => entry.extracted.status === "review") ? "review" : sourceCells.every((entry) => entry.extracted.status === "missing") ? "missing" : "extracted";
    return {
      row_id: row.row_id ?? `${table.id}-r${String(rowIndex + 1).padStart(3, "0")}`,
      line_number: lineIndex >= 0 ? cellValue(lineIndex, "quantity") : valueObject(parsed, null, null, "quantity"),
      identifier: canonicalId,
      description: cellValue(descriptionIndex, "text"),
      unit: cellValue(unitIndex, "unit"),
      quantity: cellValue(quantityIndex, "quantity"),
      plan_quantity: plannedIndex >= 0 ? cellValue(plannedIndex, "quantity") : valueObject(parsed, null, null, "quantity"),
      actual_quantity: actualIndex >= 0 ? cellValue(actualIndex, "quantity") : valueObject(parsed, null, null, "quantity"),
      unit_price: cellValue(unitPriceIndex, "money"),
      amount: cellValue(amountIndex, "money"),
      source_cells: sourceCells,
      row_status: rowStatus,
    };
  });
}

function inferHeaderKind(header) {
  const key = canonical(header);
  if (/единиц|^ед изм$|^ед$/.test(key)) return "unit";
  if (/колич|кол\s*во|план|факт|объем/.test(key)) return "quantity";
  if (/цена|сумм|стоимость|итого|к оплате/.test(key)) return "money";
  if (/дата|срок/.test(key)) return "date";
  if (/код|идентификатор|артикул|договор|номер/.test(key)) return "identifier";
  return "text";
}

function mappingRoleIsSupported(table, mapping) {
  if (!mapping || !Array.isArray(mapping.columns)) return false;
  const keys = new Set(mapping.columns.map((column) => column.semantic_key));
  const semanticSourceIds = new Map();
  for (const column of mapping.columns) if (column.semantic_key !== "unknown") semanticSourceIds.set(column.semantic_key, column.source_element_id);
  if (semanticSourceIds.size !== [...semanticSourceIds.values()].filter((sourceId, index, values) => values.indexOf(sourceId) === index).length) return false;
  const rows = table.rows ?? [];
  const hasContent = rows.some((row) => (row.cells ?? []).some((cell) => clean(cell.text ?? cell.value)));
  if (!hasContent) return false;
  if (mapping.role === "line_items") {
    const headers = (table.headers ?? []).map(canonical);
    const metadataLike = /реквизит|метаданн|metadata/i.test(String(table.caption ?? ""))
      || (/^(реквизит|поле|параметр)$/.test(headers[0] ?? "") && /^(значение|value|содержание)$/.test(headers[1] ?? ""));
    if (metadataLike) return false;
    const hasIdentityOrDescription = keys.has("identifier") || keys.has("line_number") || keys.has("description");
    const hasMeasure = ["unit", "planned_quantity", "actual_quantity", "quantity", "unit_price", "amount"].some((key) => keys.has(key));
    return hasIdentityOrDescription && hasMeasure;
  }
  if (mapping.role === "payment_schedule") return (keys.has("amount") || keys.has("unit_price")) && (keys.has("description") || keys.has("identifier") || keys.has("line_number"));
  if (mapping.role === "amendments") return keys.has("parameter") && keys.has("old_value") && keys.has("new_value");
  if (mapping.role === "metadata") return (table.headers ?? []).length <= 3;
  if (mapping.role === "summary") return /итог|сводн|summary/i.test(String(table.caption ?? ""));
  if (mapping.role === "reference") return /справоч|классифик|перечень единиц/i.test(String(table.caption ?? ""));
  if (mapping.role === "appendix") return /приложен|appendix/i.test(String(table.caption ?? ""));
  return false;
}

function extractedTables(parsed, tables, type, llm) {
  return tables.map((table) => {
    const mapping = llm?.table_mappings?.find((item) => item.table_id === table.id);
    const validRefs = new Set((table.header_cells ?? []).flatMap((cell) => cell.source_available === false ? [] : [cell.id, ...(cell.source_element_ids ?? [])]));
    const hasGroundedMappings = (mapping?.columns ?? []).length > 0 && mapping.columns.every((column) => validRefs.has(column.source_element_id));
    const validatedRole = mapping && hasGroundedMappings && mappingRoleIsSupported(table, mapping);
    const role = validatedRole ? mapping.role : table.role ?? "table";
    const working = { ...table, role };
    const repeatHeaders = [];
    const summaryRows = [];
    const emptyRows = [];
    const dataRows = [];
    for (const row of table.rows ?? []) {
      const cells = (row.cells ?? []).map((cell) => clean(cell.text ?? cell.value));
      const normalizedHeaders = (table.headers ?? []).map(canonical);
      const normalizedCells = cells.map(canonical);
      const repeatedHeader = normalizedHeaders.length > 0 && normalizedCells.length >= normalizedHeaders.length
        && normalizedHeaders.every((header, index) => header && header === normalizedCells[index]);
      if (repeatedHeader) repeatHeaders.push(row);
      else if (!cells.some(Boolean)) emptyRows.push(row);
      else if (/^(итого|всего|подытог|промежуточный итог|total)\b/i.test(cells.find(Boolean) ?? "")) summaryRows.push(row);
      else dataRows.push(row);
    }
    const semanticMapping = validatedRole && ["line_items", "payment_schedule", "amendments"].includes(role);
    const normalizeRows = (rows) => lineItems(parsed, { ...working, rows }, { llm: semanticMapping ? llm : null });
    return {
      id: table.id,
      title: table.caption ?? table.id,
      role,
      role_source: validatedRole ? "llm_grounded_headers_and_row_shape" : "rules_or_parser",
      headers: table.headers ?? [],
      rows: normalizeRows(dataRows),
      repeated_header_rows: normalizeRows(repeatHeaders),
      summary_rows: normalizeRows(summaryRows),
      empty_rows: normalizeRows(emptyRows),
      source: { source_type: table.source_type, source_ref: table.source_ref, page_numbers: table.page_numbers ?? [], sheet_name: table.sheet_name ?? null },
    };
  });
}

function amendmentRows(parsed, tables, llm) {
  return tables.filter((table) => table.role === "amendments").flatMap((table) => {
    const mapping = table.role_source === "llm_grounded_headers_and_row_shape" ? llm?.table_mappings?.find((item) => item.table_id === table.id) : null;
    const headerRefs = new Set((table.header_cells ?? []).flatMap((cell) => cell.source_available === false ? [] : [cell.id, ...(cell.source_element_ids ?? [])]));
    const mapped = new Map();
    for (const column of mapping?.columns ?? []) {
      if (!headerRefs.has(column.source_element_id)) continue;
      const index = table.header_cells.findIndex((cell) => cell.id === column.source_element_id || cell.source_element_ids?.includes(column.source_element_id));
      if (index >= 0 && !mapped.has(column.semantic_key)) mapped.set(column.semantic_key, index);
    }
    const indexOf = (key, fallback) => mapped.get(key) ?? fallback;
    const parameterIndex = indexOf("parameter", findHeader(table.headers, /пункт|условие|параметр|показател/));
    const oldIndex = indexOf("old_value", findHeader(table.headers, /редакци.{0,4}до|стар.{0,8}значен|прежн|до изменения|действующая редакция/));
    const newIndex = indexOf("new_value", findHeader(table.headers, /нов.{0,8}редакц|нов.{0,8}значен|после изменения|в новой редакции/));
    const reasonIndex = indexOf("reason", findHeader(table.headers, /основан|причин|примечан|обоснован/));
    return table.rows.map((row) => {
      const byColumn = (index) => index < 0 ? null : row.source_cells?.find((cell) => cell.column === index)?.extracted ?? row.source_cells?.[index]?.extracted ?? null;
      const asText = (index) => {
        const source = byColumn(index);
        if (!source) return valueObject(parsed, null, null, "text");
        return { ...source, value: source.source_value, normalization_note: source.status === "review" ? source.normalization_note : null };
      };
      // lineItems() already normalized every source cell and attached its provenance.
      // Re-reading row.cells here loses that normalized source_cells shape.
      const sourceCells = row.source_cells ?? [];
      const values = {
        parameter: asText(parameterIndex),
        old_value: asText(oldIndex),
        new_value: asText(newIndex),
        reason: asText(reasonIndex),
      };
      return {
        row_id: row.row_id,
        ...values,
        source_cells: sourceCells,
        row_status: amendmentRowStatus(values, sourceCells),
      };
    });
  });
}

function amendmentRowStatus(values, sourceCells) {
  const amendmentValues = [values.parameter, values.old_value, values.new_value, values.reason];
  if (amendmentValues.some((value) => value.status === "review") || sourceCells.some((cell) => cell.extracted.status === "review")) return "review";
  if (amendmentValues.every((value) => value.status === "missing")) {
    return sourceCells.every((cell) => cell.extracted.status === "missing") ? "missing" : "review";
  }
  return amendmentValues.some((value) => value.status === "missing") ? "review" : "extracted";
}

function collectReviewAndMissing(fields, tables, changes = []) {
  const missing = [];
  const review = [];
  for (const [key, field] of Object.entries(fields)) {
    if (field.status === "missing") missing.push(key);
    if (field.status === "review") review.push({ path: `fields.${key}`, reason: field.normalization_note ?? "Нужна проверка источника", source_value: field.source_value, provenance: field.provenance });
  }
  for (const table of tables) for (const [rowIndex, row] of table.rows.entries()) {
    if (table.role === "amendments") continue;
    for (const [cellIndex, cell] of row.source_cells.entries()) {
      if (cell.extracted.status === "review") review.push({ path: `tables.${table.id}.rows.${rowIndex}.cells.${cellIndex}`, reason: cell.extracted.normalization_note ?? "Нужна проверка источника", source_value: cell.extracted.source_value, provenance: cell.extracted.provenance });
    }
  }
  for (const row of changes) {
    for (const key of ["parameter", "old_value", "new_value", "reason"]) {
      const field = row[key];
      const path = `changes.${row.row_id}.${key}`;
      if (field.status === "missing") missing.push(path);
      if (field.status === "missing" || field.status === "review") {
        review.push({
          path,
          reason: field.normalization_note ?? (field.status === "missing" ? "Обязательное значение дополнительного соглашения отсутствует" : "Нужна проверка источника"),
          source_value: field.source_value,
          provenance: field.provenance,
        });
      }
    }
  }
  return { missing, review };
}

function indicators(fields, tables) {
  const preferred = ["reported_total", "contract_amount", "amount_due", "total_amount", "new_amount", "registry_total", "vat_amount", "reporting_period"];
  const rows = [];
  for (const key of preferred) if (fields[key] && fields[key].status !== "missing") rows.push({ key, label: fields[key].label ?? key, extracted: fields[key] });
  const itemRows = tables.find((table) => table.role === "line_items")?.rows ?? [];
  rows.push({ key: "extracted_line_count", label: "Извлечено строк", extracted: { value: String(itemRows.length), source_value: String(itemRows.length), status: "extracted", confidence: 1, provenance: null, normalization_note: "Количество строк структурированной таблицы" } });
  return rows;
}

function outputKey(type) {
  return type === "contract" ? "payment_schedule" : type === "addendum" ? "changes" : "line_items";
}

export function compareExtractionResults(rulesResult, llmResult) {
  const matches = [];
  const discrepancies = [];
  const rulesOnly = [];
  const llmOnly = [];
  const fieldKeys = new Set([...Object.keys(rulesResult.fields ?? {}), ...Object.keys(llmResult.fields ?? {})]);
  const same = (left, right) => JSON.stringify(left?.value ?? null) === JSON.stringify(right?.value ?? null)
    && left?.status === right?.status
    && JSON.stringify(left?.source_value ?? null) === JSON.stringify(right?.source_value ?? null)
    && JSON.stringify(left?.provenance ?? null) === JSON.stringify(right?.provenance ?? null);
  for (const key of fieldKeys) {
    const left = rulesResult.fields?.[key];
    const right = llmResult.fields?.[key];
    const record = { path: `fields.${key}`, rules: left ?? null, llm: right ?? null };
    if (!left || left.status === "missing") { if (right && right.status !== "missing") llmOnly.push(record); }
    else if (!right || right.status === "missing") rulesOnly.push(record);
    else if (same(left, right)) matches.push(record);
    else discrepancies.push(record);
  }
  const changeMap = (result) => new Map((result.changes ?? []).map((row, index) => [row.row_id ?? `change-${index + 1}`, row]));
  const leftChanges = changeMap(rulesResult);
  const rightChanges = changeMap(llmResult);
  for (const rowId of new Set([...leftChanges.keys(), ...rightChanges.keys()])) {
    const left = leftChanges.get(rowId);
    const right = rightChanges.get(rowId);
    const fields = ["parameter", "old_value", "new_value", "reason"];
    const record = { path: `changes.${rowId}`, rules: left ?? null, llm: right ?? null };
    if (!left) { llmOnly.push(record); continue; }
    if (!right) { rulesOnly.push(record); continue; }
    const differingFields = fields.filter((field) => !same(left[field], right[field]));
    const missingFields = fields.filter((field) => !left[field] || !right[field] || left[field].status === "missing" || right[field].status === "missing");
    if (differingFields.length) discrepancies.push({ ...record, differing_fields: differingFields, ...(missingFields.length ? { missing_fields: missingFields } : {}) });
    else matches.push(record);
  }
  const rowMap = (result) => {
    const changeIds = new Set((result.changes ?? []).map((row, index) => row.row_id ?? `change-${index + 1}`));
    return new Map(Object.entries(result)
      .filter(([key, collection]) => key !== "changes" && Array.isArray(collection))
      .flatMap(([, collection]) => collection)
      .filter((row) => row && typeof row === "object" && row.row_id && !changeIds.has(row.row_id))
      .map((row) => [row.row_id, row]));
  };
  const leftRows = rowMap(rulesResult);
  const rightRows = rowMap(llmResult);
  for (const rowId of new Set([...leftRows.keys(), ...rightRows.keys()])) {
    const left = leftRows.get(rowId);
    const right = rightRows.get(rowId);
    const record = { path: `rows.${rowId}`, rules: left ?? null, llm: right ?? null };
    if (!left) { llmOnly.push(record); continue; }
    if (!right) { rulesOnly.push(record); continue; }
    const fields = ["identifier", "description", "unit", "quantity", "plan_quantity", "actual_quantity", "unit_price", "amount"];
    const differingFields = fields.filter((field) => !same(left[field], right[field]));
    if (differingFields.length) discrepancies.push({ ...record, differing_fields: differingFields });
    else matches.push(record);
  }
  return {
    method: "rules_vs_llm_assisted",
    matches,
    discrepancies,
    rules_only: rulesOnly,
    llm_only: llmOnly,
    counts: { matches: matches.length, discrepancies: discrepancies.length, rules_only: rulesOnly.length, llm_only: llmOnly.length },
  };
}

export function extractStructuredDocument(parsed, options = {}) {
  if (!parsed || typeof parsed !== "object") throw new Error("Parser result must be a JSON object");
  const source = adapted(parsed);
  const documentId = source.document_id;
  const llm = options.llm ?? null;
  const mode = options.mode ?? (llm ? "llm_assisted" : "rules_only");
  const modelClassification = llm?.document_type ? { document_type: llm.document_type, confidence: llm.classification_confidence } : null;
  const typeResult = classifyDocument(parsed, modelClassification);
  const registration = schemaRegistry[typeResult.type];
  if (!registration) throw new Error("Document type is not supported by the extraction schemas");
  const tables = source.tables;
  const fields = Object.fromEntries(fieldsByType[typeResult.type].map((definition) => {
    const extracted = fieldValue(parsed, tables, definition, llm, mode);
    extracted.extracted.label = definition[1];
    return [extracted.key, extracted.extracted];
  }));
  const parsedTables = extractedTables(parsed, tables, typeResult.type, llm);
  const targetTables = parsedTables.filter((table) => ["line_items", "payment_schedule", "amendments"].includes(table.role));
  const rows = typeResult.type === "addendum" ? amendmentRows(parsed, parsedTables, llm) : targetTables.flatMap((table) => table.rows);
  const { missing, review } = collectReviewAndMissing(fields, parsedTables, typeResult.type === "addendum" ? rows : []);
  const result = {
    extraction_id: options.extractionId ?? globalThis.crypto.randomUUID(),
    document_id: documentId,
    version: options.version ?? 1,
    schema_version: registration.version,
    extracted_at: options.extractedAt ?? new Date().toISOString(),
    document_type: typeResult.type,
    mode,
    classification: typeResult,
    extraction_engine: {
      rules_executed: true,
      llm: {
        provider: llm?.provider ?? "not_called",
        model: llm?.model ?? null,
        called: Boolean(llm?.called),
        response_validated: Boolean(llm?.response_validated),
        duration_ms: llm?.duration_ms ?? null,
        usage: llm?.usage ?? null,
        validation_status: llm?.validation_status ?? (llm?.response_validated ? "valid" : "not_run"),
        error: llm?.error ?? null,
      },
      parser_adapter: source.adapter_version,
    },
    fields,
    tables: parsedTables,
    indicators: indicators(fields, parsedTables),
    missing_fields: missing,
    review_required: review,
    [outputKey(typeResult.type)]: rows,
  };
  return validateExtraction(typeResult.type, result);
}

export function parserJsonShapeErrors(value) {
  return parserInputShapeErrors(value);
}

export function normalizeDate(raw) { return dateResult(raw); }
export function normalizeMoney(raw, currencyHint = null) { return normalize(raw, "money", { currencyHint }); }
export function normalizeUnit(raw) { return normalize(raw, "unit"); }

