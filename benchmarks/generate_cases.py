"""Generate public synthetic fixtures; expected answers are declared independently."""
import json
from copy import deepcopy
from pathlib import Path

PERIOD = {'start': '2026-01-01', 'end': '2026-01-31'}


def field(value, ref):
    return {'value': value, 'source_value': json.dumps(value, ensure_ascii=False), 'status': 'extracted',
            'provenance': {'source_ref': ref, 'source_part_id': ref, 'source_available': True}}


def primary(identifier, amount, text='Административное сопровождение', agreement='DEMO-2026', day='2026-01-15'):
    return {'id': identifier, 'parser_document_id': identifier, 'file_name': identifier + '.pdf', 'role': 'primary',
            'extraction_result': {'fields': {'contract_reference': field(agreement, identifier + '-contract'),
                'document_date': field(day, identifier + '-date'), 'act_number': field(identifier, identifier + '-number'),
                'total_amount': field({'amount': amount, 'currency': 'RUB'}, identifier + '-amount'),
                'source_text_1': field(text, identifier + '-text')}, 'indicators': [], 'tables': []}}


def case(identifier, actual='120000', documents=None, expected='120000.00', status='matched', difference='0.00', categories=None):
    report = {'id': 'report', 'parser_document_id': 'report', 'file_name': 'synthetic-report.xlsx', 'role': 'kfz',
              'extraction_result': {'fields': {'contract_reference': field('DEMO-2026', 'r-contract'), 'reporting_period': field(PERIOD, 'r-period')},
                'indicators': [{'label': 'Общехозяйственные затраты', 'extracted': field({'amount': actual, 'currency': 'RUB'}, 'r-amount')}], 'tables': []}}
    return {'id': identifier, 'project': {'id': identifier, 'verification_scope': {}},
            'documents': [report, *(documents or [primary('act-1', '70000'), primary('act-2', '50000')])],
            'expected': {'status': status, 'expected': expected, 'difference': difference, 'categories': categories or []}}


def generate():
    cases = [case('01-independent-sum'), case('02-proven-difference', actual='132500', status='mismatch', difference='12500.00')]
    original = primary('act', '120000')
    copy = deepcopy(original); copy.update(id='copy', parser_document_id='copy', file_name='copy.png')
    copy['extraction_result']['fields']['source_text_1'] = field('Административное сопровождение. Повторный скан.', 'copy-text')
    cases.append(case('03-ocr-duplicate', documents=[original, copy], categories=['duplicate_operation']))
    cases.append(case('04-wrong-period', documents=[original, primary('june', '90000', day='2026-06-01')], categories=['wrong_period']))
    cases.append(case('05-other-agreement', documents=[original, primary('other', '90000', agreement='OTHER')], categories=['incorrect_document_link']))
    missing = case('06-unknown-period', expected=None, status='insufficient_data', difference=None)
    missing['documents'][0]['extraction_result']['fields'].pop('reporting_period'); cases.append(missing)
    cases.append(case('07-negative-adjustment', documents=[primary('base', '130000'), primary('credit', '-10000')]))
    currency = primary('usd', '120000'); currency['extraction_result']['fields']['total_amount']['value']['currency'] = 'USD'
    cases.append(case('08-currency-conflict', documents=[currency], expected=None, status='insufficient_data', difference=None))
    cases.append(case('09-half-up-rounding', actual='-10.01', documents=[primary('credit', '-10.005')], expected='-10.01'))
    conflict = deepcopy(original); conflict.update(id='conflict', parser_document_id='conflict')
    conflict['extraction_result']['fields']['total_amount']['value']['amount'] = '121000'
    cases.append(case('10-operation-conflict', documents=[original, conflict], expected=None, status='insufficient_data', difference=None, categories=['needs_review']))
    ambiguous = deepcopy(original); ambiguous.update(id='ambiguous', parser_document_id='ambiguous')
    ambiguous['extraction_result']['fields']['supplier_inn'] = field('1111111111', 'supplier')
    cases.append(case('11-supplier-ambiguity', documents=[original, ambiguous], expected=None, status='insufficient_data', difference=None))
    first, second = deepcopy(original), deepcopy(original)
    first['extraction_result']['fields']['supplier_inn'] = field('1111111111', 'inn-1')
    second.update(id='second', parser_document_id='second')
    second['extraction_result']['fields']['supplier_inn'] = field('2222222222', 'inn-2')
    cases.append(case('12-different-suppliers', actual='240000', documents=[first, second], expected='240000.00'))
    for identifier, amount, currency in [('13-unverified-materials', '500', 'RUB'), ('14-unverified-zero', '0', None)]:
        item = case(identifier, documents=[original], expected=None, status='insufficient_data', difference=None)
        report = item['documents'][0]['extraction_result']
        report['indicators'].append({'label': 'Материалы', 'extracted': field({'amount': amount, 'currency': currency}, 'materials')})
        if identifier == '14-unverified-zero': report['indicators'][-1]['extracted']['status'] = 'review'
        report['indicators'].append({'label': 'ИТОГО', 'extracted': field({'amount': '120000', 'currency': 'RUB'}, 'total')})
        item['target_label'] = 'ИТОГО'; cases.append(item)
    payroll = case('15-incomplete-payroll', actual='100', documents=[primary('payroll', '100', 'Оплата труда')], expected=None, status='insufficient_data', difference=None)
    payroll['documents'][0]['extraction_result']['indicators'][0]['label'] = 'Оплата труда'; cases.append(payroll)
    return {'dataset': 'phystech-trace-public-synthetic-v1', 'scope': 'local calculation after extraction; no OCR or LLM calls', 'cases': cases}


if __name__ == '__main__':
    Path(__file__).with_name('cases.json').write_text(json.dumps(generate(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
