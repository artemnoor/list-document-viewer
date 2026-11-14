import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent))
from run_e2e import validate_compact_relations

def fixture():
    docs=[{'file_name':name,'document_id':str(i)} for i,name in enumerate(['synthetic_kfz_report.pdf','synthetic_acceptance_act.docx','synthetic_primary_register.xlsx'])]
    def evidence(path,value): return {'source':{'path':path,'raw_value':value},'target':{'path':path,'raw_value':value}}
    links=[{'relationship_type':'arbitrary descriptive name','source_document_id':a,'target_document_id':b,'evidence':[evidence('fields.total.value.amount','1180300')]} for a,b in [('0','1'),('0','2'),('1','2')]]
    links.append({'source_document_id':'1','target_document_id':'2','evidence':[evidence('tables[0].rows[0].'+path,value) for path,value in [('description.value','Обследование насосного узла № 4'),('quantity.value','1'),('amount.value.amount','286500')]]})
    return links,docs

def test_descriptive_relation_names_require_exact_totals_and_joint_work_evidence():
    links,docs=fixture()
    assert len(validate_compact_relations(links,docs))==4

def test_missing_known_row_fails():
    links,docs=fixture()
    with pytest.raises(AssertionError):validate_compact_relations(links[:-1],docs)

def test_wrong_amount_fails_even_with_valid_relationship_label():
    links,docs=fixture();links[0]['evidence'][0]['target']['raw_value']='1180301'
    with pytest.raises(AssertionError):validate_compact_relations(links,docs)

def test_exact_source_values_with_numeric_grouping_are_valid_evidence():
    links,docs=fixture()
    for evidence in links[-1]['evidence']:
        for side in ['source','target']:
            evidence[side]['path']=evidence[side]['path'].replace('.value.amount','.source_value').replace('.value','.source_value')
            if evidence[side]['raw_value']=='286500':evidence[side]['raw_value']='286 500'
    assert len(validate_compact_relations(links,docs))==4
