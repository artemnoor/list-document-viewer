from gateway.financial_audit import audit


def test_downloaded_report_has_readable_amounts_statuses_and_document_links():
    from gateway.financial_audit import markdown_report
    source = {"file_name": "Акт.pdf", "document_id": "source-1", "value": {"amount": "12500.00", "currency": "RUB"}, "provenance": {"page_no": 2}, "source_path": "#/fields/total_amount"}
    result = {"project_id": "p", "conclusion": {"text": "Есть расхождение"}, "documents": [], "indicators": [{"label": "Затраты", "actual": "13000", "expected": "12500", "difference": "500", "currency": "RUB", "status": "mismatch", "reason": "Проверьте сумму", "actual_source": source, "sources": [source]}]}
    report = markdown_report(result, {"status": "rejected", "decided_at": "2026-11-14", "comment": "Исправить сумму"}, "http://localhost:8080/")
    assert "Отчёт отклонён" in report and "Исправить сумму" in report
    assert "12 500,00 ₽" in report and "Расхождение" in report
    assert "http://localhost:8080/api/projects/p/sources/source-1#page=2" in report
    assert "mismatch" not in report and "'amount':" not in report and "#/fields/" not in report


def field(value, ref):
    return {"value": value, "source_value": str(value), "status": "extracted", "provenance": {"source_ref": ref, "source_part_id": ref, "source_available": True}}


def document(identifier, role, fields, indicators=None):
    return {"id": identifier, "role": role, "file_name": identifier + ".pdf", "parser_document_id": identifier, "extraction_result": {"fields": fields, "indicators": indicators or [], "tables": []}}


def test_financial_audit_aggregates_independent_documents_and_keeps_unknown_quantity():
    report = document("report", "kfz", {"contract_reference": field("X-1", "r-contract")}, [{"label": "Общехозяйственные затраты 3 этап 2026", "extracted": field({"amount": "305.00", "currency": "RUB"}, "r-amount")}, {"label": "Трудоемкость 3 этап 2026", "extracted": field("12", "r-effort")}])
    primary = [document(name, "primary", {"contract_reference": field("X-1", name+"-contract"), "document_date": field("2026-02-01", name+"-date"), "total_amount": field({"amount": amount, "currency": "RUB"}, name+"-amount"), "source_text_1": field("Административное сопровождение и документооборот", name+"-text")}) for name, amount in [("a", "100.00"), ("b", "200.00")]]
    project = {"id": "p", "verification_scope": {"report_row": "3 этап 2026", "period_start": "2026-01-01", "period_end": "2026-05-31"}}
    result = audit(project, [report, *primary])
    row = result["indicators"][0]
    assert row["expected"] == "300.00" and row["difference"] == "5.00" and row["status"] == "mismatch"
    assert len(row["sources"]) == 2 and all(s["source_path"].startswith("#/fields/") for s in row["sources"])
    assert result["indicators"][1]["status"] == "insufficient_data"
    assert result["conclusion"]["has_proven_mismatch"] is True


def test_missing_document_or_wrong_agreement_never_becomes_zero_expected():
    report = document("report", "kfz", {"contract_reference": field("X-1", "r-contract")}, [{"label": "Общехозяйственные затраты", "extracted": field({"amount": "100", "currency": "RUB"}, "r-amount")}])
    wrong = document("wrong", "primary", {"contract_reference": field("Y-2", "c"), "total_amount": field({"amount": "100", "currency": "RUB"}, "a"), "source_text_1": field("Административное сопровождение", "t")})
    result = audit({"id":"p"}, [report, wrong])
    assert result["indicators"][0]["expected"] is None
    assert result["indicators"][0]["status"] == "insufficient_data"
    assert result["documents"][0]["category"] == "incorrect_document_link"


def test_unrecognized_category_and_missing_month_prevent_a_false_match():
    report = document("r", "kfz", {"contract_reference": field("X", "c")}, [{"label": "Оплата труда", "extracted": field({"amount": "100", "currency": "RUB"}, "v")}])
    primary = document("p", "primary", {"project_reference": field("X", "p-c"), "reporting_period": field({"start": "2026-01-01", "end": "2026-01-31"}, "p-d"), "total_amount": field({"amount": "100", "currency": "RUB"}, "p-a"), "source_text_1": field("Оплата труда", "p-t")})
    result = audit({"id": "project", "verification_scope": {"period_start": "2026-01-01", "period_end": "2026-02-28"}}, [report, primary])
    assert result["indicators"][0]["expected"] is None
    assert result["indicators"][0]["status"] == "insufficient_data"


def test_primary_total_and_its_components_are_never_added_together():
    from gateway.financial_audit import document_amount
    primary = document("p", "primary", {})
    primary["extraction_result"]["tables"] = [{"rows": [{"source_cells": [{"header":"Описание", "extracted": field(label,"d"+label)}, {"header":"Сумма, руб.","extracted": field({"amount":amount,"currency":"RUB"},"a"+label)}]} for label,amount in [("Основная", "80"),("Доплата", "20"),("ИТОГО", "100")]]}]
    values,error=document_amount(primary,'payroll')
    assert error is None and len(values)==1 and values[0]['value']['amount']=='100'


def test_mixed_currencies_and_review_values_cannot_become_matched():
    report = document("r", "kfz", {"contract_reference":field("X","c")}, [{"label":"Общехозяйственные затраты", "extracted":field({"amount":"100", "currency":"RUB"},"r-a")}])
    primary = document("p", "primary", {"contract_reference":field("X","p-c"),"source_text_1":field("Административное сопровождение","p-t"),"total_amount":field({"amount":"100","currency":"USD"},"p-a")})
    result=audit({"id":"project"},[report,primary])
    assert result['indicators'][0]['expected'] is None
    assert result['indicators'][0]['status']=='insufficient_data'
    primary['extraction_result']['fields']['total_amount']['status']='review'
    result=audit({"id":"project"},[report,primary])
    assert result['indicators'][0]['status']=='insufficient_data'


def test_source_signs_and_decimal_rounding_are_preserved():
    report=document('r','kfz',{'contract_reference':field('X','c')},[{'label':'Общехозяйственные затраты','extracted':field({'amount':'-10.01','currency':'RUB'},'r-a')}])
    primary=document('p','primary',{'contract_reference':field('X','p-c'),'source_text_1':field('Административное сопровождение','p-t'),'total_amount':field({'amount':'-10.005','currency':'RUB'},'p-a')})
    report['extraction_result']['fields']['reporting_period'] = field({'start': '2026-01-01', 'end': '2026-01-31'}, 'r-period')
    primary['extraction_result']['fields']['document_date'] = field('2026-01-15', 'p-date')
    row=audit({'id':'project'},[report,primary])['indicators'][0]
    assert row['expected']=='-10.01' and row['status']=='matched'


def test_repeated_parent_header_does_not_compare_its_subcolumns_to_the_whole_category():
    report=document('r','kfz',{'contract_reference':field('X','r-c')},[{'label':'Затраты на оплату труда - всего 2026','extracted':{**field({'amount':v,'currency':'RUB'},'r-'+str(c)), 'provenance':{'source_ref':'r-'+str(c),'source_part_id':'r-'+str(c),'column_index':c,'row_id':'row'}}} for c,v in [(4,'100'),(5,'70'),(6,'30')]])
    primary=document('p','primary',{'project_reference':field('X','c'),'source_text_0':field('Оплата труда','t'),'total_amount':field({'amount':'100','currency':'RUB'},'a')})
    report['extraction_result']['fields']['reporting_period'] = field({'start': '2026-01-01', 'end': '2026-01-31'}, 'r-period')
    primary['extraction_result']['fields']['reporting_period'] = field({'start': '2026-01-01', 'end': '2026-01-31'}, 'p-period')
    rows=audit({'id':'project'},[report,primary])['indicators']
    assert rows[0]['status']=='matched'
    assert all(r['status']=='insufficient_data' for r in rows[1:])


def test_distinct_subcolumn_labels_do_not_compare_payroll_parts_to_whole_total():
    labels = ['Оплата труда — всего 2026', 'Оплата труда — основная 2026', 'Оплата труда — дополнительная 2026']
    report = document('r', 'kfz', {'contract_reference': field('X', 'r-c')}, [
        {'label': label, 'extracted': {**field({'amount': value, 'currency': 'RUB'}, 'r-' + str(column)), 'provenance': {'source_ref': 'r-' + str(column), 'source_part_id': 'r-' + str(column), 'column_index': column, 'row_id': 'row', 'table_id': 'table'}}}
        for label, column, value in zip(labels, [4, 5, 6], ['100', '70', '30'])
    ])
    primary = document('p', 'primary', {'project_reference': field('X', 'c'), 'source_text_0': field('Оплата труда', 't'), 'total_amount': field({'amount': '100', 'currency': 'RUB'}, 'a')})
    report['extraction_result']['fields']['reporting_period'] = field({'start': '2026-01-01', 'end': '2026-01-31'}, 'r-period')
    primary['extraction_result']['fields']['reporting_period'] = field({'start': '2026-01-01', 'end': '2026-01-31'}, 'p-period')
    rows = audit({'id': 'project'}, [report, primary])['indicators']
    assert rows[0]['status'] == 'matched'
    assert all(row['status'] == 'insufficient_data' and row['expected'] is None for row in rows[1:])
