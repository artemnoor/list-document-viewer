from io import BytesIO

import pytest
from pypdf import PdfReader
from fastapi import HTTPException, Request

from gateway import main
from gateway.pdf_report import pdf_report


@pytest.fixture
def project():
    source = {'document_id': 'source-1', 'file_name': 'Акт <118>.pdf', 'value': {'amount': '100', 'currency': 'RUB'}, 'provenance': {'page_no': 2}}
    row = {'label': 'Общепроизводственные затраты', 'status': 'mismatch', 'actual': '110', 'expected': '100', 'difference': '10', 'currency': 'RUB', 'actual_source': source, 'sources': [source], 'reason': ''}
    return {'id': 'test-project', 'name': 'Проверка <отчёта>', 'documents': [source], 'verification_scope': {}, 'financial_audit': {'indicators': [row, {**row, 'label': 'ИТОГО'}], 'documents': []}, 'report_decision': {'status': 'rejected', 'comment': 'Исправить сумму <110>', 'decided_at': '2026-11-14', 'outdated': False}}


def test_pdf_has_cyrillic_readable_amounts_decision_and_original_document_links(project):
    data = pdf_report(project, project['report_decision'], 'http://localhost:8080/')
    assert data.startswith(b'%PDF-')
    reader = PdfReader(BytesIO(data))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'Отчёт отклонён' in text and 'Исправить сумму <110>' in text
    assert 'Завышение: 10,00 ₽' in text
    assert 'Расхождений по статьям: 1' in text
    links = [annotation.get_object()['/A']['/URI'] for page in reader.pages for annotation in page.get('/Annots', []) if '/A' in annotation.get_object()]
    assert 'http://localhost:8080/api/projects/test-project/sources/source-1#page=2' in links
    assert 'source_path' not in text and "'amount':" not in text


def test_stale_decision_is_not_presented_as_current_acceptance(project):
    decision = {**project['report_decision'], 'status': 'accepted', 'outdated': True}
    reader = PdfReader(BytesIO(pdf_report(project, decision)))
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'Требуется новое решение' in text and 'Отчёт принят' not in text


def test_article_difference_is_not_claimed_as_verified_grand_total(project):
    total = project['financial_audit']['indicators'][1]
    total.update(status='insufficient_data', expected=None, difference=None)
    reader = PdfReader(BytesIO(pdf_report(project)))
    text = reader.pages[0].extract_text()
    assert 'Разница по статье: 10,00 ₽' in text
    assert 'Завышение:' not in text


def test_pdf_endpoint_returns_inline_pdf_without_stale_browser_cache(monkeypatch, project):
    monkeypatch.setattr(main, 'project_payload', lambda _: project)
    request = Request({'type': 'http', 'scheme': 'http', 'server': ('localhost', 8080), 'path': '/', 'headers': []})
    response = main.financial_audit_pdf(project['id'], request)
    assert response.media_type == 'application/pdf'
    assert response.body.startswith(b'%PDF-')
    assert response.headers['cache-control'] == 'no-store'


def test_pdf_endpoint_cannot_export_unchecked_project(monkeypatch, project):
    project['financial_audit'] = None
    monkeypatch.setattr(main, 'project_payload', lambda _: project)
    with pytest.raises(HTTPException) as error:
        main.financial_audit_pdf(project['id'], None)
    assert error.value.status_code == 409


def test_multi_source_report_has_no_empty_pages(project):
    source = project['financial_audit']['indicators'][0]['sources'][0]
    for label in ['Оплата труда', 'Страховые взносы', 'Общехозяйственные затраты']:
        project['financial_audit']['indicators'].append({'label': label, 'status': 'matched', 'actual': '100', 'expected': '100', 'difference': '0', 'currency': 'RUB', 'sources': [{**source, 'file_name': f'{label}_ведомость_{index}_2026.xlsx'} for index in range(5)]})
    reader = PdfReader(BytesIO(pdf_report(project)))
    assert all(len(page.extract_text().strip()) > 80 for page in reader.pages)
