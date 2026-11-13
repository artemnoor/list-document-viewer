"""Evidence retained for displayed OCR hypotheses; no value is auto-confirmed."""
from copy import deepcopy


def attach_cell_evidence(table):
    provenance=table.get('provenance',[])
    for cell in table.get('cells',[]):
        uncertain = bool(cell.get('correction') or cell.get('recognition_candidates') or cell.get('requires_review'))
        original=cell.get('raw_text',cell.get('text',''))
        selected=cell.get('text','')
        candidates=deepcopy(cell.get('recognition_candidates') or [{'source':'original','value':original}])
        if uncertain and selected != original and len(candidates) == 1:
            candidates.append({'source':cell.get('correction','ocr'),'value':selected})
        confirmed=cell.get('confirmation_status')=='confirmed'
        cell['original_value']=original
        cell['candidates']=candidates
        cell['selected_value']=selected
        cell['verified_value']=selected if confirmed else None
        cell['verification_status']='confirmed' if confirmed else ('needs_review' if uncertain else 'not_verified')
        cell['requires_review']=uncertain and not confirmed
        cell['source_refs']=[{'page_no':p.get('page_no'),
                              'bbox':deepcopy(cell.get('bbox') or p.get('bbox')),
                              'scope':('inferred_cell' if cell.get('bbox_basis') == 'inferred' else 'cell') if cell.get('bbox') else 'table'} for p in provenance]
