import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_detects_three_aligned_numeric_rows_and_retains_source_boxes():
    from aligned_ocr_tables import candidates_from_text
    parts=[]
    for row, values in enumerate([['Код','Название','Сумма'],['1','Кабель','35000'],['2','Датчик','85000'],['3','Плата','15000']]):
        for col,value in enumerate(values):
            left,top = [10,100,300][col], 20+row*40
            parts.append({'kind':'text','text':value,'source':'ocr_text',
                          'provenance':[{'page_no':1,'bbox':{'l':left,'t':top,'r':left+50,'b':top+20,'coord_origin':'TOPLEFT'}}]})
    result=candidates_from_text({'pages':{'1':{'size':{'width':500,'height':500}}},'parts':parts})
    assert len(result)==1
    assert result[0]['rows'][2] == ['2','Датчик','85000']
    assert result[0]['cells'][5]['bbox'] == [300,60,350,80]
    assert result[0]['table_warning']


def test_two_column_prose_or_unaligned_numbers_do_not_form_table():
    from aligned_ocr_tables import candidates_from_text
    parts=[]
    for row in range(4):
        for col,text in enumerate(['Примечание','в 2026 году']):
            left,top=20+col*200,20+row*40
            parts.append({'kind':'text','text':text,'source':'ocr_text','provenance':[{'page_no':1,'bbox':{'l':left,'t':top,'r':left+100,'b':top+20}}]})
    assert candidates_from_text({'pages':{'1':{'size':{'width':500,'height':500}}},'parts':parts})==[]


def test_existing_table_is_not_overlaid_by_text_hypothesis():
    from aligned_ocr_tables import merge_missing_tables
    box={'l':10,'t':10,'r':400,'b':200,'coord_origin':'TOPLEFT'}
    table={'kind':'table','rows':[['a']],'cells':[{'row':0,'column':0,'text':'a'}], 'provenance':[{'page_no':1,'bbox':box}]}
    layout={'pages':{'1':{'size':{'width':500,'height':500}}},'parts':[table]}
    merged, additions=merge_missing_tables(layout, layout)
    assert merged == layout
    assert additions == []


def test_unassigned_text_inside_inferred_table_region_is_not_lost():
    from pdf_layout import merge_model_layout
    prov=lambda l,t,r,b: [{'page_no':1,'bbox':{'l':l,'t':t,'r':r,'b':b,'coord_origin':'TOPLEFT'}}]
    source={'kind':'text','source':'ocr_text','text':'100','provenance':prov(10,10,40,20)}
    note={'kind':'text','source':'ocr_text','text':'Примечание','provenance':prov(10,30,70,40)}
    table={'kind':'table','source':'ocr_text_alignment','rows':[['100']],
           'cells':[{'row':0,'column':0,'text':'100','bbox':[10,10,40,20]}],
           'provenance':prov(0,0,100,50)}
    layout={'pages':{'1':{'size':{'width':100,'height':100}}},'parts':[source,note]}
    result=merge_model_layout(layout,[table])
    assert any(part.get('text')=='Примечание' for part in result['parts'])
    assert not any(part.get('text')=='100' for part in result['parts'])
