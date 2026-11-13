import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_vl_table_output_keeps_region_and_does_not_invent_cell_boxes():
    from parsers.vl_adapter import candidates_from_result
    output={'parsing_res_list':[{'block_label':'table','block_bbox':[10,20,90,60],
                                'block_content':'<table><tr><td>Сумма</td><td>35000</td></tr></table>'}]}
    table=candidates_from_result(output,page_no=2,scale_x=.5,scale_y=.5,version='v1.5')[0]
    assert table['rows']==[['Сумма','35000']]
    assert table['source']=='paddleocr_vl_v1.5'
    assert table['provenance'][0]['bbox']['r']==45
    assert all('bbox' not in cell for cell in table['cells'])
    assert table['table_warning']


def test_vl_rejects_unknown_versions():
    import pytest
    from parsers.vl_adapter import candidates_from_result
    with pytest.raises(ValueError):
        candidates_from_result({},page_no=1,version='latest')


def test_vl_comparison_uses_explicit_version_and_local_backend(monkeypatch):
    import types
    from PIL import Image
    import ocr_layout
    from parsers.vl_adapter import parse_pages
    seen={}
    class Pipeline:
        def __init__(self, **kwargs): seen.update(kwargs)
        def predict(self, image): return []
    monkeypatch.setitem(sys.modules,'paddleocr',types.SimpleNamespace(PaddleOCRVL=Pipeline))
    monkeypatch.setattr(ocr_layout,'_page_image',lambda *a:Image.new('RGB',(2,2),'white'))
    result=parse_pages('x.png','.png',{'pages':{'1':{'size':{'width':2,'height':2}}}},[1],'v1.6')
    assert result == []
    assert seen['pipeline_version']=='v1.6'
    assert seen['vl_rec_backend']=='native'
    assert seen['device']=='cpu'


def test_image_page_layout_is_in_original_pixel_coordinates(tmp_path):
    from PIL import Image
    from parsers.vl_adapter import page_layout
    source=tmp_path/'sample.png'
    Image.new('RGB',(123,87),'white').save(source)
    assert page_layout(source)=={'pages':{'1':{'size':{'width':123,'height':87}}}}
