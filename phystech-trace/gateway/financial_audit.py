"""Conservative, source-based audit of explicit cost categories. No answer keys or model calls."""
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
import re

LOGGER = logging.getLogger(__name__)

RULES = {
    "payroll": ("Оплата труда", r"оплат[аыу] труд|заработн.{0,12}плат"),
    "insurance": ("Страховые взносы", r"страхов.{0,15}взнос|начислено взносов"),
    "production": ("Общепроизводственные затраты", r"общепроизводствен|производствен.{0,30}наклад|наклад.{0,30}производствен|лабораторн.{0,25}(?:комплекс|оборудован)|испытательн.{0,20}стенд|специализированн.{0,30}(?:измерительн.{0,20})?оборудован"),
    "administration": ("Общехозяйственные затраты", r"общехозяйствен|административн|информационно.аналитическ.{0,50}управлен|организационн.{0,20}управлен"),
}


def number(value):
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def money(value):
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def usable(wrapper):
    return isinstance(wrapper, dict) and wrapper.get("status") == "extracted" and isinstance(wrapper.get("provenance"), dict) and wrapper["provenance"].get("source_available") is not False


def category(text):
    text = text.casefold().replace("ё", "е")
    if re.search(RULES["insurance"][1], text):
        return "insurance"
    if re.search(RULES["payroll"][1], text):
        return "payroll"
    hits = [key for key in ("production", "administration") if re.search(RULES[key][1], text)]
    return hits[0] if len(hits) == 1 else None


def source(doc, path, wrapper, label=None):
    return {"document_id": doc["parser_document_id"], "file_name": doc["file_name"], "source_path": path, "value": wrapper.get("value"), "source_value": wrapper.get("source_value"), "extraction_status": wrapper.get("status"), "provenance": wrapper.get("provenance"), "label": label}


def doc_text(extraction):
    fields = extraction.get("fields") or {}
    texts = [str(v.get("value") or "") for k, v in fields.items() if k.startswith("source_text_")]
    for table in extraction.get("tables") or []:
        texts.extend(str(c.get("extracted", {}).get("value") or "") for row in table.get("rows") or [] for c in row.get("source_cells") or [])
    return " ".join(texts)


def contract(fields):
    for key in ("contract_reference", "contract_number", "project_reference"):
        wrapper = fields.get(key) or {}
        if usable(wrapper) and isinstance(wrapper.get("value"), str):
            return wrapper["value"].casefold().strip(), key
    return None, None


def period(fields):
    for key in ("execution_period", "reporting_period", "act_date", "document_date", "invoice_date", "report_date"):
        wrapper = fields.get(key) or {}
        if not usable(wrapper):
            continue
        value = wrapper.get("value")
        left, right = (value.get("start"), value.get("end")) if isinstance(value, dict) else (value, value)
        try:
            left, right = date.fromisoformat(str(left)), date.fromisoformat(str(right))
            if left <= right:
                return left, right, key
        except ValueError:
            pass
    return None, None, None


def audit_period(scope, fields):
    """A report creation date is not its accounting period."""
    if scope.get("period_start") and scope.get("period_end"):
        return date.fromisoformat(str(scope["period_start"])), date.fromisoformat(str(scope["period_end"])), "settings"
    candidates = []
    for key in ("reporting_period", "execution_period"):
        wrapper = fields.get(key) or {}
        if usable(wrapper) and isinstance(wrapper.get("value"), dict):
            left, right, _ = period({key: wrapper})
            if left and right:
                candidates.append((left, right))
    if candidates and len(set(candidates)) == 1:
        return *candidates[0], "report"
    return None, None, "unknown"


def operation_identity(fields, agreement, left, right, group):
    """Use business identifiers, never OCR text or amount, to identify an operation."""
    def normalized(keys):
        for key in keys:
            wrapper = fields.get(key) or {}
            if usable(wrapper) and wrapper.get("value"):
                return re.sub(r"\s+", " ", str(wrapper["value"]).casefold()).strip()
        return None

    identifier = normalized(("act_number", "document_number", "invoice_number"))
    if not identifier or not left or not right:
        return None
    supplier = normalized(("supplier_inn", "contractor_inn", "seller_inn"))
    supplier = ("inn", supplier) if supplier is not None else None
    if supplier is None:
        name = normalized(("supplier", "contractor", "seller"))
        supplier = ("name", name) if name is not None else None
    return agreement, identifier, left, right, group, supplier


def is_total(label):
    return bool(re.search(r"итого|[hн]то[гr]о|общие затраты|всего затрат", label, re.I))


def covers_period(intervals, start, end):
    cursor = start.toordinal()
    for left, right in sorted(intervals):
        if left.toordinal() > cursor:
            return False
        cursor = max(cursor, right.toordinal() + 1)
    return cursor > end.toordinal()


def document_amount(doc, group):
    extraction = doc["extraction_result"]
    candidates = []
    for key in ("amount_due", "total_amount", "registry_total"):
        wrapper = (extraction.get("fields") or {}).get(key)
        if usable(wrapper) and isinstance(wrapper.get("value"), dict) and wrapper["value"].get("currency"):
            candidates.append(source(doc, f"#/fields/{key}", wrapper, key))
    if candidates:
        values = {(number(c["value"]), c["value"]["currency"]) for c in candidates}
        if len(values) == 1:
            return candidates[:1], None
        return [], "Несколько различных итоговых сумм документа"
    cells = []
    for ti, table in enumerate(extraction.get("tables") or []):
        for ri, row in enumerate(table.get("rows") or []):
            row_label = " | ".join(str(c.get("extracted", {}).get("value") or "") for c in row.get("source_cells") or [] if not isinstance(c.get("extracted", {}).get("value"), dict))
            for ci, cell in enumerate(row.get("source_cells") or []):
                wrapper = cell.get("extracted") or {}
                header = cell.get("header") or ""
                if not usable(wrapper) or not isinstance(wrapper.get("value"), dict) or not wrapper["value"].get("currency"):
                    continue
                if re.search(r"база|ндс|налоговая база", header, re.I):
                    continue
                if group == "insurance" and not re.search(r"взнос|начислено|сумм", header, re.I):
                    continue
                cells.append(source(doc, f"#/tables/{ti}/rows/{ri}/source_cells/{ci}/extracted", wrapper, row_label))
    totals = [s for s in cells if re.search(r"(?:^|[ |])(?:итого|всего)(?:$|[ |])", s["label"], re.I)]
    if len(totals) == 1:
        return totals, None
    if totals:
        return [], "Неоднозначные итоги нескольких таблиц"
    if len(cells) == 1 or group in {"payroll", "insurance"} and cells:
        return cells, None
    return [], "Не найдена однозначная подтверждённая сумма"


def audit(project, documents):
    scope = project.get("verification_scope") or {}
    report = next((d for d in documents if d["role"] == "kfz" and d.get("extraction_result")), None)
    if not report:
        return None
    report_fields = report["extraction_result"].get("fields") or {}
    expected_contract, _ = contract(report_fields)
    start, end, period_source = audit_period(scope, report_fields)
    groups = defaultdict(list)
    findings = list(project.get("upload_diagnostics") or [])
    unresolved = []
    periods = defaultdict(list)
    seen_operations = defaultdict(list)
    for doc in documents:
        if doc["role"] == "kfz":
            continue
        extraction = doc.get("extraction_result") or {}
        fields = extraction.get("fields") or {}
        own_contract, contract_key = contract(fields)
        left, right, period_key = period(fields)
        group = category(doc_text(extraction))
        item = {"document_id": doc["parser_document_id"], "file_name": doc["file_name"], "category": None, "included": False, "source_url": f"/api/projects/{project['id']}/sources/{doc['parser_document_id']}"}
        if expected_contract and own_contract and own_contract != expected_contract:
            item.update(category="incorrect_document_link", message="Документ другого договора", source_path=f"#/fields/{contract_key}")
        elif start and end and left and right and (right < start or left > end):
            item.update(category="wrong_period", message="Документ вне проверяемого периода", source_path=f"#/fields/{period_key}")
        elif not expected_contract or own_contract != expected_contract or start and (not left or not right or left < start or right > end):
            item.update(category="missing_supporting_document", message="Недостаточно реквизитов для включения документа")
            unresolved.append((group, item))
        elif not group:
            item.update(category="needs_review", message="Статья затрат не определяется однозначно по содержанию")
            unresolved.append((None, item))
        else:
            amounts, error = document_amount(doc, group)
            if error:
                item.update(category="needs_review", message=error)
                unresolved.append((group, item))
            else:
                currencies = {s["value"].get("currency") for s in amounts}
                if len(currencies) != 1 or any(number(s["value"]) is None for s in amounts):
                    item.update(category="needs_review", message="Неоднозначная валюта или сумма")
                    unresolved.append((group, item))
                else:
                    identity = operation_identity(fields, own_contract, left, right, group)
                    signature = (sum((number(s["value"]) for s in amounts), Decimal(0)), next(iter(currencies)))
                    candidates = seen_operations[identity[:-1]] if identity else []
                    supplier = identity[-1] if identity else None
                    previous = next((candidate for candidate in candidates if candidate["supplier"] == supplier), None)
                    ambiguous = next((candidate for candidate in candidates
                                      if not supplier or not candidate["supplier"]
                                      or supplier[0] != "inn" or candidate["supplier"][0] != "inn"), None) if previous is None else None
                    if previous and signature == previous["signature"]:
                        item.update(category="duplicate_operation", message="Повторная операция: номер, период, договор, поставщик и сумма совпадают", original_document_id=previous["document_id"])
                    elif previous:
                        item.update(category="needs_review", message="Разные суммы или валюты одной операции", original_document_id=previous["document_id"])
                        unresolved.append((group, item))
                    elif ambiguous:
                        item.update(category="needs_review", message="Недостаточно согласованных реквизитов поставщика для различения операций", original_document_id=ambiguous["document_id"])
                        unresolved.append((group, item))
                    else:
                        if identity:
                            candidates.append({"signature": signature, "document_id": doc["parser_document_id"], "supplier": supplier})
                        classification_evidence = [source(doc, f"#/fields/{key}", wrapper, "Содержание операции") for key, wrapper in fields.items() if usable(wrapper) and isinstance(wrapper.get("value"), str) and re.search(RULES[group][1], wrapper["value"], re.I)]
                        for value in amounts:
                            value["classification_evidence"] = classification_evidence
                            value["source_url"] = item["source_url"]
                            value["inclusion_reason"] = f"{RULES[group][0]}: содержание операции, договор и период согласованы"
                        groups[group].extend(amounts)
                        periods[group].append((left, right))
                        item.update(category="included", included=True, message=f"Включён: {RULES[group][0]}", sources=amounts)
        findings.append(item)
    selector = set(re.findall(r"[a-zа-яё]+|\d+", (scope.get("report_row") or "").casefold())) - {"г", "год", "года"}
    selected_indicators = [indicator for indicator in report["extraction_result"].get("indicators") or []
                           if not selector or selector <= set(re.findall(r"[a-zа-яё]+|\d+", (indicator.get("label") or indicator.get("key") or "").casefold()))]
    declared_groups = set()
    unsupported_costs = []
    for indicator in selected_indicators:
        wrapper = indicator.get("extracted") or {}
        value = wrapper.get("value")
        label = indicator.get("label") or indicator.get("key") or ""
        if not isinstance(value, dict) or "amount" not in value or is_total(label) and not category(label):
            continue
        group = category(label)
        if group:
            declared_groups.add(group)
            if number(value) is None:
                unsupported_costs.append(label)
        elif number(value) != 0 or not usable(wrapper):
            # An exact, grounded zero contributes nothing to the total. A nonzero
            # unsupported expense (or an unreadable value) prevents its verification.
            unsupported_costs.append(label)
    rows = []
    seen_targets = set()
    first_columns = {}
    for indicator in report["extraction_result"].get("indicators") or []:
        wrapper = indicator.get("extracted") or {}
        prov = wrapper.get("provenance") or {}
        column = prov.get("column_index")
        if isinstance(column, int):
            value = wrapper.get("value")
            # Extractors may append distinct child headings to a shared expense
            # category. Their columns still belong to the same row subtotal.
            parent = category(indicator.get("label") or "") if isinstance(value, dict) and value.get("currency") else None
            key = (parent or indicator.get("label"), prov.get("table_id"), prov.get("row_id"))
            first_columns[key] = min(first_columns.get(key, column), column)
    for index, indicator in enumerate(report["extraction_result"].get("indicators") or []):
        label = indicator.get("label") or indicator.get("key") or ""
        if indicator.get("key") == "extracted_line_count" or selector and not selector <= set(re.findall(r"[a-zа-яё]+|\d+", label.casefold())):
            continue
        wrapper = indicator.get("extracted") or {}
        actual = number(wrapper.get("value"))
        if actual is None:
            continue
        origin = wrapper.get("provenance") or {}
        identity = (origin.get("source_ref"), origin.get("source_part_id"), str(wrapper.get("value")))
        if identity in seen_targets:
            continue
        seen_targets.add(identity)
        value = wrapper.get("value")
        monetary = isinstance(value, dict) and value.get("currency")
        group = category(label) if monetary else None
        total = bool(monetary and not group and is_total(label))
        selected_groups = [key for key in RULES if key in declared_groups] if total else [group] if group else []
        sources = [s for key in selected_groups for s in groups[key]]
        gaps = []
        if not start or not end:
            gaps.append("Не определён проверяемый период: задайте его в настройках или подтвердите период отчёта")
        if total:
            gaps.extend(f"Не подтверждена статья общего итога: {name}" for name in unsupported_costs)
            if any(groups[key] and key not in declared_groups for key in RULES):
                gaps.append("В первичных документах есть статьи, не сопоставленные со структурой общего итога")
        parent_key = (group or label, origin.get("table_id"), origin.get("row_id"))
        column = origin.get("column_index")
        if isinstance(column, int) and parent_key in first_columns and column > first_columns[parent_key]:
            gaps.append("Подколонка общего заголовка требует отдельной расшифровки, не сравнивается с итогом статьи")
        if not monetary or not selected_groups:
            gaps.append("Нет отдельного набора первичных данных для подтверждения этого показателя")
        if re.search(r"тыс[. ]|миллион|млн", label, re.I):
            gaps.append("Масштаб единицы требует отдельного правила преобразования")
        if not usable(wrapper):
            gaps.append("Значение отчёта требует проверки распознавания")
        for key in selected_groups:
            if not groups[key]:
                gaps.append(f"Нет подтверждений: {RULES[key][0]}")
            if any(g is None or g == key for g, _ in unresolved):
                gaps.append(f"Есть неразрешённые документы: {RULES[key][0]}")
            if key in {"payroll", "insurance"} and start and end:
                if not covers_period(periods[key], start, end):
                    gaps.append(f"Неполный набор месячных расчётов: {RULES[key][0]}")
        if monetary and any(s["value"].get("currency") != value.get("currency") for s in sources):
            gaps.append("Валюты источников и отчёта различаются")
        expected = sum((number(s["value"]) for s in sources), Decimal(0)) if sources and not gaps else None
        difference = Decimal(money(actual)) - Decimal(money(expected)) if expected is not None else None
        status = "insufficient_data" if gaps else "matched" if difference.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == 0 else "mismatch"
        rows.append({"target_id": f"indicator-{index}", "label": label, "status": status, "actual": money(actual) if monetary else str(actual), "expected": money(expected) if expected is not None else None, "difference": money(difference) if difference is not None else None, "currency": value.get("currency") if monetary else None, "category": "amount_difference" if status == "mismatch" else "missing_supporting_document" if gaps else None, "actual_source": source(report, f"#/indicators/{index}/extracted", wrapper, label), "sources": sources, "formula": " + ".join(money(number(s["value"])) for s in sources) if expected is not None else None, "information_gaps": gaps, "reason": "; ".join(gaps) if gaps else "Сумма независимых источников сопоставлена с отчётом после фильтрации договора, периода и дублей"})
    # Retain numeric subcolumns omitted by the semantic extractor as explicitly
    # unverified. Their original table wrapper is the citation, never an invented value.
    selected_origins = {(r["actual_source"]["provenance"] or {}).get("source_ref") for r in rows}
    for ti, table in enumerate(report["extraction_result"].get("tables") or []):
        for ri, row in enumerate(table.get("rows") or []):
            cells = row.get("source_cells") or []
            row_label = str((cells[0].get("extracted") or {}).get("value") or "") if cells else ""
            if selector and not selector <= set(re.findall(r"[a-zа-яё]+|\d+", row_label.casefold())):
                continue
            if not selector and not re.search(r"этап|период|год", row_label, re.I):
                continue
            for ci, cell in enumerate(cells[1:], 1):
                wrapper = cell.get("extracted") or {}
                provenance = wrapper.get("provenance") or {}
                if not provenance or provenance.get("source_ref") in selected_origins:
                    continue
                raw = wrapper.get("value")
                raw_number = number(raw)
                if raw_number is None and isinstance(raw, str) and re.fullmatch(r"[+-]?\d[\d \u00a0\u202f]*[.,]\d+", raw):
                    raw_number = number(raw.replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace(",", "."))
                if raw_number is None:
                    continue
                label = f"{cell.get('header') or 'Подпоказатель'}, {row_label} (столбец {ci + 1})"
                rows.append({"target_id": f"detail-{ti}-{ri}-{ci}", "label": label, "status": "insufficient_data", "actual": str(raw_number), "expected": None, "difference": None, "currency": raw.get("currency") if isinstance(raw, dict) else None, "category": "missing_supporting_document", "actual_source": source(report, f"#/tables/{ti}/rows/{ri}/source_cells/{ci}/extracted", wrapper, label), "sources": [], "formula": None, "information_gaps": ["Отдельная первичная расшифровка подпоказателя отсутствует"], "reason": "Отдельная первичная расшифровка подпоказателя отсутствует"})
                selected_origins.add(provenance.get("source_ref"))
    # An overall total inherits gaps of its main expense components. Child
    # breakdown columns are not additional expenses and do not block a supported
    # parent subtotal; numeric nonmonetary metrics are independent of the cost sum.
    component_gaps = []
    for row in rows:
        original = row["actual_source"]
        value = original.get("value")
        if (row["status"] != "insufficient_data" or not isinstance(value, dict) or "amount" not in value
                or is_total(row["label"]) and not category(row["label"])
                or any(gap.startswith("Подколонка общего заголовка") for gap in row["information_gaps"])):
            continue
        if category(row["label"]) or number(value) != 0 or original.get("extraction_status") != "extracted":
            component_gaps.append(row["label"])
    for row in rows:
        if row.get("currency") and not category(row["label"]) and is_total(row["label"]) and component_gaps:
            row["information_gaps"].extend(f"Не подтверждена составляющая итога: {label}" for label in component_gaps)
            row.update(status="insufficient_data", expected=None, difference=None, formula=None,
                       category="missing_supporting_document", reason="; ".join(row["information_gaps"]))
    counts = dict(Counter(r["status"] for r in rows))
    LOGGER.info("[FIX:financial-audit] project=%s indicators=%d matched=%d mismatch=%d insufficient=%d period_source=%s duplicates=%d unresolved=%d", project["id"], len(rows), counts.get("matched", 0), counts.get("mismatch", 0), counts.get("insufficient_data", 0), period_source, sum(item.get("category") == "duplicate_operation" for item in findings), len(unresolved))
    effective_scope = {**scope, "period_start": start.isoformat() if start else None, "period_end": end.isoformat() if end else None, "period_source": period_source}
    return {"engine": "local-cost-audit/1.1", "project_id": project["id"], "scope": effective_scope, "indicators": rows, "documents": findings, "summary": counts, "conclusion": {"has_proven_mismatch": counts.get("mismatch", 0) > 0, "coverage_complete": bool(rows) and not counts.get("insufficient_data"), "text": f"Расхождений: {counts.get('mismatch', 0)}; совпадает: {counts.get('matched', 0)}; недостаточно данных: {counts.get('insufficient_data', 0)}. Подтверждены только проверенные показатели. Расхождения статьи и общего итога не суммируются."}}


def markdown_report(result, decision=None, base_url=""):
    def escape(value):
        return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ").replace("[", "\\[").replace("]", "\\]")

    def amount(value, currency=None):
        if value is None:
            return "—"
        if isinstance(value, dict):
            currency = value.get("currency", currency)
            value = value.get("amount")
        parsed = number(value)
        if parsed is None:
            return escape(value)
        formatted = f"{parsed:,.2f}".replace(",", " ").replace(".", ",")
        return formatted + (" ₽" if currency == "RUB" else f" {currency}" if currency else "")

    def document_link(item):
        title = escape(item.get("file_name", "Документ"))
        identifier = item.get("document_id") or (item.get("provenance") or {}).get("document_id")
        if not identifier:
            return title
        from urllib.parse import quote
        url = f"{base_url.rstrip('/')}/api/projects/{quote(result['project_id'], safe='')}/sources/{quote(identifier, safe='')}"
        page = (item.get("provenance") or {}).get("page_no")
        return f"[{title}]({url + '#page=' + str(page) if page else url})"

    labels = {"matched": "Совпадает", "mismatch": "Расхождение", "insufficient_data": "Нет подтверждения", "needs_review": "Нужна проверка"}
    lines = ["# Заключение о достоверности отчёта", "", result["conclusion"]["text"], "", "Недостаток данных не означает ошибку. Расхождение статьи и его влияние на общий итог учитываются один раз.", ""]
    if decision:
        status = "Требует пересмотра после изменения расчёта" if decision.get("outdated") else "Отчёт принят" if decision["status"] == "accepted" else "Отчёт отклонён"
        lines.extend(["## Решение по отчёту", "", status, "", "Дата решения: " + escape(decision.get("decided_at")), "", escape(decision.get("comment") or "Без комментария"), ""])
    else:
        lines.extend(["Решение по отчёту ещё не принято.", ""])
    lines.extend(["## Показатели", "", "| Показатель | В отчёте | Подтверждено документами | Разница | Результат |", "|---|---:|---:|---:|---|"])
    for row in result["indicators"]:
        values = [escape(row["label"]), *[amount(row.get(key), row.get("currency")) for key in ("actual", "expected", "difference")], labels.get(row["status"], "Нужна проверка")]
        lines.append("| " + " | ".join(values) + " |")
    for row in result["indicators"]:
        lines.extend(["", "## " + escape(row["label"]), "", labels.get(row["status"], "Нужна проверка") + ". " + row["reason"]])
        if row.get("actual_source"):
            lines.extend(["", "Исходный отчёт: " + document_link(row["actual_source"])])
        if row.get("formula"):
            lines.extend(["", "Расчёт: " + row["formula"]])
        for item in row["sources"]:
            loc = item.get("provenance") or {}
            location = f"лист {loc.get('sheet_name')}, ячейка {loc.get('cell_address')}" if loc.get("sheet_name") else f"страница {loc['page_no']}" if loc.get("page_no") else "фрагмент документа"
            lines.append(f"- {document_link(item)}: **{amount(item.get('value'), row.get('currency'))}**; {escape(location)}")
    lines.extend(["", "## Учёт документов", ""])
    lines.extend(f"- {escape(item['file_name'])}: {item.get('message') or item.get('category')}" for item in result["documents"])
    return "\n".join(lines) + "\n"
