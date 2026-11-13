"""A single Markdown source for preview and download."""
from markdown_it import MarkdownIt
from html import escape
import bleach
import re

def literal(value):
    """Native text is data, never author-provided Markdown or HTML markup."""
    return re.sub(r'([\\`*_[\]{}])', r'\\\1', escape(str(value), quote=False))


def cell(value, markdown=False):
    text=escape(str(value if value is not None else '')).replace('|', '&#124;').replace('\n', '<br>')
    return re.sub(r'([\\`*_[\]{}])', r'\\\1', text) if markdown else text


def table(rows, cells=None, force_html=False, first_row_header=True):
    if not rows: return ''
    if force_html or (cells and any(c.get('row_span',1)>1 or c.get('col_span',1)>1 or c.get('nested_tables') for c in cells)):
        if not cells:
            cells=[{'row':r,'column':c,'text':str(value or '')} for r,row in enumerate(rows) for c,value in enumerate(row)]
        output=['<table>']
        for ri in range(len(rows)):
            output.append('<tr>')
            for c in sorted((c for c in cells if c['row']==ri), key=lambda c:c['column']):
                tag='th' if ri==0 and first_row_header else 'td'
                content=cell(c['text'])
                for nested in c.get('nested_tables',[]): content+=table(nested['rows'],nested['cells'],force_html=True)
                output.append(f'<{tag} rowspan="{c.get("row_span",1)}" colspan="{c.get("col_span",1)}">{content}</{tag}>')
            output.append('</tr>')
        output.append('</table>')
        return '\n'.join(output)
    width = max(len(row) for row in rows)
    padded = [list(row) + [''] * (width - len(row)) for row in rows]
    lines = ['| ' + ' | '.join(cell(c,markdown=True) for c in row) + ' |' for row in padded]
    lines.insert(1, '| ' + ' | '.join(['---'] * width) + ' |')
    return '\n'.join(lines)


def _append_accepted_additions(text, result):
    additions=[]
    for edit in result.get('accepted_document_edits',[]):
        value=edit.get('proposed')
        if edit.get('action')=='add_text' and isinstance(value,str) and value.strip() and value.strip() not in text:
            additions.append(literal(value.strip()))
    return text.rstrip() + ('\n\n' if text.strip() else '') + '\n\n'.join(additions) + ('\n' if additions or text else '')


def structured_markdown(result):
    layout = result.get('visual_layout', {})
    if layout.get('parts'):
        blocks, previous, first_heading = [], None, True
        for part in layout['parts']:
            if part.get('annotation_only'):
                continue
            if part.get('rows'):
                blocks.append(table(part['rows'],part.get('cells'), force_html=bool(part.get('continuation_of_page')), first_row_header=not part.get('continuation_of_page'))); previous=None; continue
            text = part.get('text', '').strip()
            if part['kind'] == 'link':
                target = part.get('target', text)
                from urllib.parse import urlparse, quote
                if urlparse(target).scheme.lower() in {'http','https','mailto'}:
                    blocks.append(f'[{literal(text)}]({quote(target, safe=":/?#=&%+@")})')
                previous=None
                continue
            if not text or part['kind'] == 'picture': continue
            text = literal(text)
            heading = part['kind'] == 'section_header'
            bullet = text.startswith(('•', '- ', '– '))
            if heading:
                text = ('# ' if first_heading else '## ') + text
                first_heading = False
            elif bullet: text = '- ' + text.lstrip('•–- ').strip()
            if previous and not heading and not bullet:
                prov = part.get('provenance', [{}])[0]; prev_prov = previous.get('provenance', [{}])[0]
                box, prev_box = prov.get('bbox', {}), prev_prov.get('bbox', {})
                gap = box.get('t', 0) - prev_box.get('b', 0)
                aligned=abs(box.get('l',0)-prev_box.get('l',0))<20
                if previous['kind'] != 'section_header' and aligned and prov.get('page_no') == prev_prov.get('page_no') and 0 <= gap < part.get('font_size', 10) * .4:
                    blocks[-1] += ' ' + text; previous = part; continue
            blocks.append(text); previous = part
        return _append_accepted_additions('\n\n'.join(blocks) + '\n', result)
    parts = result.get('parts', [])
    # Native Office tables carry merges, nested content, and exact grid coordinates.
    native = [p for p in parts if p.get('kind') in {'sheet','cell','paragraph','table','header','footer','footnote','endnote'} or p.get('source')=='docx_native']
    if native:
        blocks=[];sheet_cells=[];sheet_merges=[]
        def flush_sheet():
            if not sheet_cells: return
            min_col=min(c['column'] for c in sheet_cells);max_col=max(c['column'] for c in sheet_cells)
            min_row=min(c['row'] for c in sheet_cells);max_row=max(c['row'] for c in sheet_cells)
            from openpyxl.utils.cell import range_boundaries
            spans=[range_boundaries(m) for m in sheet_merges]
            for c1,r1,c2,r2 in spans:
                min_col=min(min_col,c1);max_col=max(max_col,c2);min_row=min(min_row,r1);max_row=max(max_row,r2)
            if (max_col-min_col+1)*(max_row-min_row+1)>100000:
                blocks.extend(f"- **{c['coordinate']}**: {c.get('value','')}" for c in sheet_cells)
            else:
                from openpyxl.utils import get_column_letter
                values={(c['row'],c['column']):c.get('display_value',c.get('value','')) for c in sheet_cells}
                rows=[['']+[get_column_letter(c) for c in range(min_col,max_col+1)]]
                rows += [[r]+[values.get((r,c),'') for c in range(min_col,max_col+1)] for r in range(min_row,max_row+1)]
                cells=[]
                for ri,row in enumerate(rows):
                    for ci,value in enumerate(row):
                        sr=ri+min_row-1;sc=ci+min_col-1
                        merge=next((m for m in spans if ri>0 and ci>0 and m[0]<=sc<=m[2] and m[1]<=sr<=m[3]),None)
                        if merge and (sc,sr)!=(merge[0],merge[1]):continue
                        cells.append({'row':ri,'column':ci,'text':str(value),'row_span':min(merge[3],max_row)-sr+1 if merge else 1,'col_span':min(merge[2],max_col)-sc+1 if merge else 1})
                blocks.append(table(rows,cells))
            sheet_cells.clear()
        for part in native:
            kind=part['kind']
            if kind=='sheet': flush_sheet();sheet_merges[:]=part.get('merged',[]);blocks.append('## '+literal(part['name']))
            elif kind=='cell': sheet_cells.append(part)
            elif part.get('rows'): blocks.append(table(part['rows'],part.get('cells')))
            elif part.get('text') and kind not in {'header','footer'}:
                style=part.get('style','').lower()
                heading=re.search(r'heading\s*(\d+)',style)
                prefix='# ' if style=='title' else '#' * min(6,int(heading[1]))+' ' if heading else ''
                text=literal(part['text'])
                for link in part.get('hyperlinks',[]):
                    from urllib.parse import urlparse, quote
                    target=link['target'];label=literal(link['text'])
                    if label and (target.startswith('#') or urlparse(target).scheme.lower() in {'http','https','mailto'}):
                        text=text.replace(label,f'[{label}]({quote(target,safe=":/?#=&%+@")})',1)
                for note in part.get('note_refs',[]):text+=f' [{"F" if note["kind"]=="footnote" else "E"}{note["id"]}]'
                if kind in {'footnote','endnote'}:prefix=f'**{"Сноска F" if kind=="footnote" else "Примечание E"}{part["id"]}.** '
                if kind=='picture':prefix='*Изображение:* '
                if part.get('list'):
                    entry=part['list'];prefix='  '*min(entry['level'],12)+('- ' if entry['format']=='bullet' else str(entry.get('start',1))+'. ')
                blocks.append(prefix+text)
        flush_sheet()
        return _append_accepted_additions('\n\n'.join(blocks).rstrip()+'\n', result)
    text=result.get('markdown','').rstrip()
    if result.get('source_extension') in {'.txt','.log','.json','.xml'}:
        text=literal(text)
    return _append_accepted_additions(text+'\n', result)


def preview_html(markdown):
    renderer = MarkdownIt('commonmark', {'html': True, 'linkify': False}).enable('table')
    return bleach.clean(renderer.render(markdown), tags=['p','h1','h2','h3','h4','h5','h6','ul','ol','li','strong','em','s','blockquote','pre','code','hr','br','table','thead','tbody','tr','th','td','a'], attributes={'a':['href','title'], 'ol':['start'], 'th':['align','rowspan','colspan'], 'td':['align','rowspan','colspan']}, protocols=['http','https','mailto'], strip=True)
