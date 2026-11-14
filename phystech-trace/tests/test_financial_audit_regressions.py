from copy import deepcopy

import pytest

from gateway.financial_audit import RULES, audit
from test_financial_audit import document, field


def inputs():
    report = document('report', 'kfz', {
        'contract_reference': field('X', 'r-contract'),
        'reporting_period': field({'start': '2026-01-01', 'end': '2026-01-31'}, 'r-period'),
    }, [{'label': RULES['administration'][0], 'extracted': field({'amount': '100', 'currency': 'RUB'}, 'r-amount')}])
    primary = document('primary', 'primary', {
        'contract_reference': field('X', 'p-contract'),
        'document_date': field('2026-01-15', 'p-date'),
        'act_number': field('A-1', 'p-number'),
        'source_text_1': field(RULES['administration'][0], 'p-text'),
        'total_amount': field({'amount': '100', 'currency': 'RUB'}, 'p-amount'),
    })
    return report, primary


def append_total(report, amount='100'):
    report['extraction_result']['indicators'].append({'label': 'ИТОГО', 'extracted': field({'amount': amount, 'currency': 'RUB'}, 'r-total')})


def copied(primary):
    copy = deepcopy(primary)
    copy.update(id='copy', parser_document_id='copy', file_name='copy.png')
    return copy


def test_copy_with_changed_ocr_text_is_counted_once_and_both_files_are_audited():
    report, primary = inputs()
    copy = copied(primary)
    copy['extraction_result']['fields']['source_text_1'] = field(RULES['administration'][0] + ' OCR отличается', 'copy-text')
    result = audit({'id': 'p'}, [report, primary, copy])
    row = result['indicators'][0]
    assert (row['status'], row['expected'], row['difference']) == ('matched', '100.00', '0.00')
    assert len(row['sources']) == 1
    assert [item['category'] for item in result['documents']] == ['included', 'duplicate_operation']
    assert result['documents'][1]['original_document_id'] == 'primary'


def test_same_operation_with_conflicting_amounts_is_unverified():
    report, primary = inputs()
    conflict = copied(primary)
    conflict['extraction_result']['fields']['total_amount'] = field({'amount': '120', 'currency': 'RUB'}, 'conflict-amount')
    row = audit({'id': 'p'}, [report, primary, conflict])['indicators'][0]
    assert row['status'] == 'insufficient_data' and row['expected'] is None


def test_same_number_from_different_identified_suppliers_is_not_a_duplicate():
    report, primary = inputs()
    primary['extraction_result']['fields']['supplier_inn'] = field('1111111111', 'inn-1')
    other = copied(primary)
    other['extraction_result']['fields']['supplier_inn'] = field('2222222222', 'inn-2')
    report['extraction_result']['indicators'][0]['extracted']['value']['amount'] = '200'
    result = audit({'id': 'p'}, [report, primary, other])
    assert result['indicators'][0]['status'] == 'matched'
    assert all(item['included'] for item in result['documents'])


@pytest.mark.parametrize('total', ['400', '450'])
def test_total_cannot_be_confirmed_or_mismatched_when_materials_are_unverified(total):
    report, primary = inputs()
    documents = []
    report['extraction_result']['indicators'] = []
    for group, (label, _) in RULES.items():
        report['extraction_result']['indicators'].append({'label': label, 'extracted': field({'amount': '100', 'currency': 'RUB'}, 'r-' + group)})
        doc = copied(primary)
        doc.update(id=group, parser_document_id=group)
        fields = doc['extraction_result']['fields']
        fields['act_number'] = field(group, group + '-number')
        fields['source_text_1'] = field(label, group + '-text')
        fields['reporting_period'] = field({'start': '2026-01-01', 'end': '2026-01-31'}, group + '-period')
        documents.append(doc)
    report['extraction_result']['indicators'].append({'label': 'Материалы', 'extracted': field({'amount': '50', 'currency': 'RUB'}, 'r-materials')})
    append_total(report, total)
    row = audit({'id': 'p'}, [report, *documents])['indicators'][-1]
    assert row['status'] == 'insufficient_data'
    assert row['expected'] is None and row['difference'] is None
    assert any('Материалы' in gap for gap in row['information_gaps'])


def test_report_period_is_used_without_manual_scope_and_excludes_next_year():
    report, primary = inputs()
    primary['extraction_result']['fields']['document_date'] = field('2027-01-15', 'p-date')
    result = audit({'id': 'p'}, [report, primary])
    assert result['documents'][0]['category'] == 'wrong_period'
    assert result['indicators'][0]['status'] == 'insufficient_data'


def test_unknown_report_period_never_produces_a_match():
    report, primary = inputs()
    report['extraction_result']['fields'].pop('reporting_period')
    row = audit({'id': 'p'}, [report, primary])['indicators'][0]
    assert row['status'] == 'insufficient_data' and row['expected'] is None


def test_manual_scope_overrides_broader_report_period():
    report, primary = inputs()
    report['extraction_result']['fields']['reporting_period'] = field({'start': '2026-01-01', 'end': '2026-12-31'}, 'r-period')
    result = audit({'id': 'p', 'verification_scope': {'period_start': '2026-02-01', 'period_end': '2026-02-28'}}, [report, primary])
    assert result['documents'][0]['category'] == 'wrong_period'


def test_partial_overlap_is_not_counted_without_proration():
    report, primary = inputs()
    primary['extraction_result']['fields']['reporting_period'] = field({'start': '2025-12-01', 'end': '2026-01-31'}, 'p-period')
    row = audit({'id': 'p'}, [report, primary])['indicators'][0]
    assert row['status'] == 'insufficient_data' and row['expected'] is None


def test_total_uses_declared_expenses_and_ignores_supported_child_breakdowns():
    report, primary = inputs()
    append_total(report)
    rows = audit({'id': 'p'}, [report, primary])['indicators']
    assert [row['status'] for row in rows] == ['matched', 'matched']
    assert rows[-1]['expected'] == '100.00'


@pytest.mark.parametrize('zero_status, expected_status', [('extracted', 'matched'), ('review', 'insufficient_data')])
def test_only_an_exact_grounded_zero_may_be_omitted_from_total(zero_status, expected_status):
    report, primary = inputs()
    zero = field({'amount': '0', 'currency': 'RUB'}, 'r-zero')
    zero['status'] = zero_status
    report['extraction_result']['indicators'].append({'label': 'Материалы', 'extracted': zero})
    append_total(report)
    assert audit({'id': 'p'}, [report, primary])['indicators'][-1]['status'] == expected_status


def test_unverified_main_component_blocks_the_total():
    report, primary = inputs()
    report['extraction_result']['indicators'][0]['extracted']['status'] = 'review'
    append_total(report)
    row = audit({'id': 'p'}, [report, primary])['indicators'][-1]
    assert row['status'] == 'insufficient_data' and row['expected'] is None


def test_payroll_for_one_day_does_not_confirm_a_whole_month():
    report, primary = inputs()
    report['extraction_result']['indicators'][0]['label'] = RULES['payroll'][0]
    primary['extraction_result']['fields']['source_text_1'] = field(RULES['payroll'][0], 'p-text')
    row = audit({'id': 'p'}, [report, primary])['indicators'][0]
    assert row['status'] == 'insufficient_data' and row['expected'] is None


def test_an_expense_subtotal_is_not_treated_as_the_overall_total():
    report, primary = inputs()
    report['extraction_result']['indicators'][0]['label'] += ' итого'
    assert audit({'id': 'p'}, [report, primary])['indicators'][0]['status'] == 'matched'


def test_missing_currency_of_main_expense_blocks_the_total():
    report, primary = inputs()
    report['extraction_result']['indicators'][0]['extracted']['value']['currency'] = None
    append_total(report)
    row = audit({'id': 'p'}, [report, primary])['indicators'][-1]
    assert row['status'] == 'insufficient_data' and row['expected'] is None


def test_monetary_expense_omitted_from_indicators_but_present_in_table_blocks_total():
    report, primary = inputs()
    append_total(report)
    report['extraction_result']['tables'] = [{'rows': [{'source_cells': [
        {'header': 'Период', 'extracted': field('3 этап 2026', 'r-row')},
        {'header': 'Материалы', 'extracted': field({'amount': '50', 'currency': 'RUB'}, 'r-materials-cell')},
    ]}]}]
    rows = audit({'id': 'p'}, [report, primary])['indicators']
    total = next(row for row in rows if row['label'] == 'ИТОГО')
    assert total['status'] == 'insufficient_data' and total['expected'] is None


@pytest.mark.parametrize('first_supplier, second_supplier', [
    ({}, {'supplier_inn': '1111111111'}),
    ({'supplier': 'Компания А'}, {'supplier_inn': '1111111111'}),
])
def test_differing_supplier_metadata_does_not_prove_independent_operations(first_supplier, second_supplier):
    report, primary = inputs()
    copy = copied(primary)
    for doc, metadata in [(primary, first_supplier), (copy, second_supplier)]:
        for key, value in metadata.items():
            doc['extraction_result']['fields'][key] = field(value, doc['id'] + '-supplier')
    row = audit({'id': 'p'}, [report, primary, copy])['indicators'][0]
    assert row['status'] == 'insufficient_data' and row['expected'] is None
