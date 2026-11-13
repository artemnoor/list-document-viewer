import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_ppstructure_converts_html_spans_and_geometry():
    from parsers.ppstructure_adapter import candidates_from_result

    result = {'table_res_list': [{
        'pred_html': '<table><tr><th colspan="2">Товар</th></tr><tr><td>А</td><td>10</td></tr></table>',
        'cell_box_list': [[10, 20, 90, 40], [10, 40, 50, 60], [50, 40, 90, 60]],
    }]}
    table = candidates_from_result(result, page_no=2, scale_x=.5, scale_y=.5)[0]
    assert table['rows'] == [['Товар', ''], ['А', '10']]
    assert table['cells'][0]['col_span'] == 2
    assert table['cells'][2]['bbox'] == [25, 20, 45, 30]
    assert table['provenance'][0]['page_no'] == 2
    assert table['provenance'][0]['bbox']['r'] == 45


def test_problem_pages_include_conflicts_and_incomplete_numeric_columns():
    from parsers.ppstructure_adapter import problem_pages
    def table(page, rows, **extra):
        return {'kind': 'table', 'rows': rows, 'provenance': [{'page_no': page}], **extra}
    layout = {'parts': [table(1, [['x']]), table(2, [['Цена'], ['5'], [''], ['10']]),
                        table(3, [['x']], arbitration={'has_conflicts': True})]}
    assert problem_pages(layout) == {2, 3}


def test_aligned_numeric_text_without_a_table_triggers_fallback():
    from parsers.ppstructure_adapter import problem_pages
    parts = [{'kind': 'text', 'text': value, 'provenance': [{'page_no': 1,
              'bbox': {'l': 100 + offset, 't': top, 'r': 130 + offset, 'b': top + 10}}]}
             for value, offset, top in [('10', 0, 20), ('25', 2, 40), ('39', -1, 60)]]
    assert problem_pages({'parts': parts}) == {1}


def test_optional_fallback_preserves_original_and_candidate(monkeypatch):
    from parsers import ppstructure_adapter as adapter
    box = {'l': 10, 't': 10, 'r': 90, 'b': 60, 'coord_origin': 'TOPLEFT'}
    original = {'kind': 'table', 'rows': [['А', '10']], 'cells': [{'row': 0, 'column': 0, 'text': 'А'}],
                'provenance': [{'page_no': 1, 'bbox': box}], 'table_warning': 'uncertain'}
    candidate = {'kind': 'table', 'source': 'ppstructure_v3', 'rows': [['А', '11']],
                 'cells': [{'row': 0, 'column': 0, 'text': 'А'}], 'provenance': [{'page_no': 1, 'bbox': box}]}
    layout = {'pages': {'1': {'size': {'width': 100, 'height': 100}}}, 'parts': [original]}
    monkeypatch.setenv('PPSTRUCTURE_ENABLED', '1')
    monkeypatch.setattr(adapter, 'parse_pages_isolated', lambda *args: [candidate])
    merged, additions, warnings = adapter.run_fallback('unused', '.pdf', layout)
    assert additions == [candidate]
    assert not warnings
    assert len(merged['parts'][0]['table_candidates']) == 2
    assert merged['parts'][0]['arbitration']['has_conflicts']


def test_optional_fallback_disabled_without_loading_model(monkeypatch):
    from parsers import ppstructure_adapter as adapter
    monkeypatch.delenv('PPSTRUCTURE_ENABLED', raising=False)
    monkeypatch.setattr(adapter, 'parse_pages_isolated', lambda *args: (_ for _ in ()).throw(AssertionError()))
    layout = {'parts': []}
    assert adapter.run_fallback('unused', '.pdf', layout) == (layout, [], [])


def test_pipeline_receives_bgr_pixels_without_page_rotation(monkeypatch):
    import types
    from PIL import Image
    from parsers import ppstructure_adapter as adapter
    seen = {}
    class Pipeline:
        def __init__(self, **kwargs):
            seen['settings'] = kwargs
        def predict(self, image):
            seen['pixel'] = image[0, 0].tolist()
            return []
    monkeypatch.setitem(sys.modules, 'paddleocr', types.SimpleNamespace(PPStructureV3=Pipeline))
    import ocr_layout
    monkeypatch.setattr(ocr_layout, '_page_image', lambda *args: Image.new('RGB', (2, 2), (255, 0, 0)))
    assert adapter.parse_pages('unused', '.png', {'pages': {'1': {'size': {'width': 2, 'height': 2}}}}, [1]) == []
    assert seen['pixel'] == [0, 0, 255]
    assert seen['settings']['use_doc_orientation_classify'] is False
    assert seen['settings']['enable_mkldnn'] is False
    assert seen['settings']['device'] == 'cpu'


def test_worker_failure_reports_diagnostic_without_discarding_base(monkeypatch):
    import subprocess
    from parsers import ppstructure_adapter as adapter
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ['worker'], stderr=b'Missing dependency: paddleocr')
    monkeypatch.setenv('PPSTRUCTURE_ENABLED','1')
    monkeypatch.setattr(adapter,'problem_pages',lambda layout:{1})
    monkeypatch.setattr(subprocess,'run',fail)
    layout={'parts':[],'pages':{'1':{'size':{'width':100,'height':100}}}}
    merged, additions, warnings=adapter.run_fallback('x.png','.png',layout)
    assert merged == layout and additions == []
    assert 'Missing dependency: paddleocr' in warnings[0]
