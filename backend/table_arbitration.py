"""Select a display candidate without treating agreement as verification."""
from copy import deepcopy
import re
from table_candidates import snapshot


def _metrics(table):
    rows=table.get('rows') or []
    nonempty=sum(bool(str('' if v is None else v).strip()) for row in rows for v in row)
    chars=sum(len(str('' if v is None else v).strip()) for row in rows for v in row)
    return {'nonempty_cells':nonempty,'empty_cells':sum(len(row) for row in rows)-nonempty,'characters':chars}


def _split_supported_header(table, peer):
    """Propose a two-part header only when both reconstructions agree on text."""
    rows,cells=table.get('rows') or [],table.get('cells') or []
    if len(rows)<2 or len(rows[0])<2:
        return
    width=len(rows[0])
    header=[cell for cell in cells if cell.get('row')==0 and str(cell.get('text','')).strip()]
    other=[cell for cell in peer.get('cells',[]) if cell.get('row')==0 and str(cell.get('text','')).strip()]
    first_column=next((cell for cell in cells if cell.get('row')==1 and cell.get('column')==0),None)
    if (len(header)!=1 or len(other)!=2 or header[0].get('column')!=0 or
        header[0].get('col_span',1)!=width or not first_column):
        return
    other.sort(key=lambda cell:(cell.get('bbox') or [float('inf')])[0])
    def valid(box):
        return isinstance(box,list) and len(box)==4 and all(isinstance(v,(int,float)) for v in box)
    if not all(valid(cell.get('bbox')) for cell in [header[0],first_column,*other]):
        return
    whole,baseline,left,right=(cell['bbox'] for cell in [header[0],first_column,*other])
    normalize=lambda value: re.sub(r'\s+','',str(value)).casefold()
    if normalize(header[0]['text'])!=normalize(other[0]['text']+other[1]['text']):
        return
    first_overlap=max(0,min(left[2],baseline[2])-max(left[0],baseline[0]))
    if first_overlap/max(1,left[2]-left[0])<.8 or right[0]<baseline[2] or not whole[0]<baseline[2]<whole[2]:
        return
    split=baseline[2]
    original=header[0]['text']
    replacement=[]
    for col,span,text,bbox in [(0,1,other[0]['text'],[whole[0],whole[1],split,whole[3]]),
                               (1,width-1,other[1]['text'],[split,whole[1],whole[2],whole[3]])]:
        replacement.append({'row':0,'column':col,'row_span':1,'col_span':span,'text':text,
                            'bbox':bbox,'bbox_basis':'inferred','raw_text':original,
                            'correction':'header_split_alignment','requires_review':True})
    table['cells']=[cell for cell in cells if cell not in header]+replacement
    table['rows'][0]=[other[0]['text'],other[1]['text']]+['']*(width-2)
    table['derivation']['header_split']='inferred_from_matching_text_and_columns'


def _trim_margin_rows(candidate, other):
    """Propose removing blank outer regions corroborated by a tighter grid."""
    if candidate.get('source') != 'ocr_raster_grid' or other.get('source') != 'ocr_raster_grid':
        return None
    def numbers(table):
        return {re.sub(r'\s+', '', str(value)) for row in table.get('rows',[]) for value in row
                if re.fullmatch(r'[+−\-]?\d[\d\s.,%]*', str(value).strip())}
    first,second=numbers(candidate),numbers(other)
    common=len(first & second)
    if common < 4 or common < .8*len(first) or common < .8*len(second):
        return None
    prov=other.get('provenance') or []
    box=prov[0].get('bbox',{}) if prov else {}
    if not all(isinstance(box.get(k),(int,float)) for k in ('t','b')):
        return None
    rows=candidate.get('rows') or []
    cells=candidate.get('cells') or []
    def removable(index):
        if any(str('' if value is None else value).strip() for value in rows[index]):
            return False
        touching=[cell for cell in cells if cell.get('row',-1) <= index < cell.get('row',-1)+cell.get('row_span',1)]
        if not touching or any(cell.get('row_span',1)!=1 or cell.get('text') for cell in touching):
            return False
        for cell in touching:
            bounds=cell.get('bbox')
            if not isinstance(bounds,list) or len(bounds)!=4 or bounds[3]<=bounds[1]:
                return False
            overlap=max(0,min(bounds[3],box['b'])-max(bounds[1],box['t']))
            if overlap/(bounds[3]-bounds[1])>.2:
                return False
        return True
    start,end=0,len(rows)
    while end-start>2 and removable(start): start+=1
    while end-start>2 and removable(end-1): end-=1
    if start==0 and end==len(rows):
        return None
    derived=deepcopy(candidate)
    derived['rows']=deepcopy(rows[start:end])
    derived['cells']=[deepcopy(cell) for cell in cells if start<=cell.get('row',-1)<end]
    for cell in derived['cells']:cell['row']-=start
    derived['derivation']={'method':'trim_empty_rows_outside_matching_grid','removed_before':start,'removed_after':len(rows)-end}
    derived['table_warning']='Пустые внешние строки исключены только в предложенном варианте; проверьте исходные таблицы.'
    _split_supported_header(derived, other)
    return derived


def arbitrate(existing, incoming):
    candidates=deepcopy(existing.get('table_candidates') or [snapshot(existing)])
    if any(c.get('source') == incoming.get('source') and c.get('rows') == incoming.get('rows')
           and c.get('cells') == incoming.get('cells') and c.get('provenance') == incoming.get('provenance') for c in candidates):
        return deepcopy(existing)
    candidates.append(snapshot(incoming))
    derived = _trim_margin_rows(candidates[0], incoming) or _trim_margin_rows(incoming, candidates[0])
    if derived:
        candidates.append(snapshot(derived))
    metrics=[_metrics(c) for c in candidates]
    # More populated cells are evidence of coverage, never proof of accuracy.
    if derived:
        selected=max(range(len(candidates)),key=lambda i:(metrics[i]['nonempty_cells']-.25*metrics[i]['empty_cells'],metrics[i]['nonempty_cells'],bool(candidates[i].get('derivation')),metrics[i]['characters']))
    else:
        selected=max(range(len(candidates)),key=lambda i:(metrics[i]['nonempty_cells'],metrics[i]['characters']))
    def fingerprint(candidate):
        values=tuple(tuple(' '.join(str('' if v is None else v).split()) for v in row) for row in candidate.get('rows',[]))
        structure=tuple(sorted((cell.get('row',-1),cell.get('column',-1),cell.get('row_span',1),cell.get('col_span',1))
                               for cell in candidate.get('cells',[])))
        return values, structure
    fingerprints=[fingerprint(c) for c in candidates]
    conflict=any(f != fingerprints[0] for f in fingerprints[1:])
    result=deepcopy(candidates[selected])
    result['table_candidates']=candidates
    result['arbitration']={'selected_index':selected,'metrics':metrics,'has_conflicts':conflict,'method':'coverage_with_empty_cell_penalty' if derived else 'nonempty_cells_then_characters','verification_status':'needs_review' if conflict else 'not_verified'}
    return result
