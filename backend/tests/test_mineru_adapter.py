import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_middle_json_table_is_a_located_unverified_candidate():
    from parsers.mineru_adapter import candidates_from_middle
    data = {'schema': 'docvortex.middle', 'schema_version': '2.0', 'pages': [
        {'page_idx': 1, 'blocks': [{'type': 'table', 'bbox': [.1, .2, .9, .5],
          'blocks': [{'type': 'table_body', 'lines': [{'spans': [
              {'type': 'table', 'html': '<table><tr><td>Товар</td><td>100</td></tr></table>'}]}]}]}]}]}
    layout = {'pages': {'2': {'size': {'width': 600, 'height': 800}}}}
    candidate = candidates_from_middle(data, layout)[0]
    assert candidate['rows'] == [['Товар', '100']]
    assert candidate['provenance'][0]['bbox']['l'] == 60
    assert candidate['provenance'][0]['bbox']['b'] == 400
    assert all('bbox' not in cell for cell in candidate['cells'])
    assert candidate['source'] == 'mineru'


def test_middle_json_rejects_unknown_protocol():
    from parsers.mineru_adapter import candidates_from_middle
    import pytest
    with pytest.raises(ValueError):
        candidates_from_middle({'schema': 'unknown', 'pages': []}, {'pages': {}})


def test_middle_json_v4_table_body_content_is_parsed():
    from parsers.mineru_adapter import candidates_from_middle
    document={'schema':'docvortex.middle','schema_version':'2.0','pages':[{'page_idx':0,'blocks':[
        {'type':'table','bbox':[.1,.2,.9,.8], 'content':[{'type':'table_body','content':'<table><tr><td>42</td></tr></table>'}]}]}]}
    layout={'pages':{'1':{'size':{'width':100,'height':200}}}}
    assert candidates_from_middle(document,layout)[0]['rows'] == [['42']]


def test_mineru_fallback_runs_only_when_enabled_and_preserves_variants(monkeypatch):
    from parsers import mineru_adapter as adapter
    box = {'l': 10, 't': 10, 'r': 90, 'b': 60, 'coord_origin': 'TOPLEFT'}
    table = {'kind': 'table', 'rows': [['10']], 'cells': [{'row': 0, 'column': 0, 'text': '10'}],
             'provenance': [{'page_no': 1, 'bbox': box}], 'table_warning': 'uncertain'}
    alternative = {'kind': 'table', 'source': 'mineru', 'rows': [['11']],
                   'cells': [{'row': 0, 'column': 0, 'text': '11'}], 'provenance': [{'page_no': 1, 'bbox': box}]}
    layout = {'pages': {'1': {'size': {'width': 100, 'height': 100}}, '2': {'size': {'width': 100, 'height': 100}}}, 'parts': [table]}
    monkeypatch.setenv('MINERU_ENABLED', '1')
    monkeypatch.setenv('MINERU_EXECUTABLE', 'mineru-kit')
    monkeypatch.setattr(adapter, 'parse_document', lambda *args: [alternative])
    merged, candidates, warnings = adapter.run_fallback('input.pdf', '.pdf', layout)
    assert not warnings and candidates == [alternative]
    assert merged['parts'][0]['arbitration']['has_conflicts']


def test_mineru_fallback_checks_proposed_multipage_continuations(monkeypatch):
    from parsers import mineru_adapter as adapter
    table1 = {'kind': 'table', 'source': 'ocr_raster_grid', 'rows': [['1', 'A'], ['2', 'B']],
              'cells': [], 'provenance': [{'page_no': 1, 'bbox': {'l': 10, 't': 70, 'r': 90, 'b': 100}}]}
    table2 = {'kind': 'table', 'source': 'ocr_raster_grid', 'rows': [['3', 'C']], 'cells': [],
              'provenance': [{'page_no': 2, 'bbox': {'l': 10, 't': 0, 'r': 90, 'b': 30}}]}
    layout = {'pages': {'1': {'size': {'width': 100, 'height': 100}},
                        '2': {'size': {'width': 100, 'height': 100}}},
              'parts': [table1, table2]}
    alternative = {'kind': 'table', 'source': 'mineru', 'rows': [['1', 'A']],
                   'cells': [{'row': 0, 'column': 0, 'text': '1'},
                             {'row': 0, 'column': 1, 'text': 'A'}],
                   'provenance': [table1['provenance'][0]]}
    calls = []
    monkeypatch.setenv('MINERU_ENABLED', '1')
    monkeypatch.setenv('MINERU_EXECUTABLE', 'mineru-kit')
    monkeypatch.setattr(adapter, 'parse_document', lambda *args: calls.append(args) or [alternative])

    merged, candidates, warnings = adapter.run_fallback('input.pdf', '.pdf', layout)

    assert len(calls) == 1
    assert not warnings and candidates == [alternative]
    assert any(part.get('arbitration', {}).get('has_conflicts') for part in merged['parts'])


def test_subprocess_uses_local_middle_json_and_timeout(monkeypatch, tmp_path):
    import json
    import subprocess
    from parsers import mineru_adapter as adapter
    seen = {}
    def run(command, **options):
        seen['command'], seen['options'] = command, options
        output = Path(command[command.index('-o') + 1])
        output.write_text(json.dumps({'schema':'docvortex.middle','schema_version':'2.0','pages':[]}), encoding='utf-8')
    monkeypatch.setattr(subprocess, 'run', run)
    assert adapter.parse_document(tmp_path / 'sample.pdf', {'pages': {}}, 'mineru-kit') == []
    assert seen['options']['shell'] is False
    assert seen['options']['timeout'] == 600
    assert '--remote' not in seen['command']
    assert seen['command'][seen['command'].index('--format') + 1] == 'middle_json'
    assert seen['options']['env']['MINERU_DEVICE_MODE']
