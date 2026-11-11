/* Render recognized content using geometry when available, structural blocks otherwise. */
function annotationCategory(kind) {
  kind = kind.toLowerCase();
  if (/table|cell|sheet/.test(kind)) return 'table';
  if (/title|heading|section_header/.test(kind)) return 'heading';
  if (/picture|image|chart/.test(kind)) return 'picture';
  if (/formula|code/.test(kind)) return 'formula';
  if (/link/.test(kind)) return 'link';
  return 'text';
}
const annotationLabels = {table:'Таблицы и ячейки',heading:'Заголовки',picture:'Изображения',formula:'Формулы и код',text:'Текст',link:'Ссылки'};
function annotationRect(box, size) {
  const top = box.coord_origin === 'BOTTOMLEFT' ? size.height - Math.max(box.t, box.b) : Math.min(box.t, box.b);
  return {left:100*Math.min(box.l,box.r)/size.width, top:100*top/size.height, width:100*Math.abs(box.r-box.l)/size.width, height:100*Math.abs(box.t-box.b)/size.height};
}
function renderAnnotations(host, result, file, api, source = 'native') {
  const create = (tag, className, text) => { const el = document.createElement(tag); if(className) el.className = className; if(text !== undefined) el.textContent = text; return el; };
  const root = create('div','annotation-view');
  const legend = create('div','annotation-legend');
  const scene = create('div','annotation-scene');
  const inspector = create('aside','annotation-inspector'); inspector.setAttribute('aria-live','polite');
  inspector.append(create('span','inspector-eyebrow','ВЫБРАННЫЙ ЭЛЕМЕНТ'), create('p','inspector-empty','Нажмите на область документа или выберите элемент из списка.'));
  const hasNative = Boolean(result.visual_layout?.parts?.length);
  const native = source === 'native' && hasNative;
  const parts = (native ? result.visual_layout.parts : source==='model' ? result.model_parts || result.parts : result.parts) || [];
  const header = create('div','annotation-header');
  header.append(create('strong','', 'Разметка документа'), create('span','annotation-total',`${parts.length} элементов`));
  if(hasNative) {
    const select = create('select','annotation-source'); select.setAttribute('aria-label','Источник разметки');
    for(const [value,label] of [['native',file.extension==='.pdf'?'Геометрия и OCR':'Строки OCR и таблицы'],['model','Блоки модели']]) { const option=create('option','',label); option.value=value; option.selected=value===source; select.append(option); }
    select.onchange=()=>{host.replaceChildren();renderAnnotations(host,result,file,api,select.value);}; header.append(select);
  }
  root.append(header);
  const elementList=create('div','annotation-elements');
  const workspace=create('div','annotation-workspace');
  const side=create('div','annotation-side'); side.append(inspector, elementList);
  const categories = new Set(parts.map(p => annotationCategory(p.kind)));
  for (const category of categories) {
    const label = create('label',`legend-item mark-${category}`), check = document.createElement('input'); check.type='checkbox'; check.checked=true;
    check.addEventListener('change', () => { for(const el of scene.querySelectorAll(`[data-category="${category}"]`)) el.hidden = !check.checked; });
    label.append(check,document.createTextNode(`${annotationLabels[category]} · ${parts.filter(p=>annotationCategory(p.kind)===category).length}`)); legend.append(label);
  }
  function inspect(part, button) {
    for(const el of scene.querySelectorAll('.mark-selected')) el.classList.remove('mark-selected');
    button.classList.add('mark-selected');
    const heading = create('strong','inspector-title',`${annotationLabels[annotationCategory(part.kind)]}${part.coordinate ? ' · '+part.coordinate : ''}`);
    const text=create('p','inspector-text',part.text || part.target || String(part.value ?? '') || 'Без текстового содержимого');
    const location=part.provenance?.[0];
    const meta=create('p','inspector-meta',location ? `Страница ${location.page_no} · ${part.source==='pdf_native' ? 'Геометрия PDF' : 'Распознавание модели'}` : part.sheet || 'Структура документа');
    const details=create('details','inspector-details'), summary=create('summary','','Технические данные'), pre=create('pre','',JSON.stringify(part,null,2));details.append(summary,pre);
    inspector.replaceChildren(create('span','inspector-eyebrow','ВЫБРАННЫЙ ЭЛЕМЕНТ'),heading,meta,text,details);
    if(part.rows) {
      text.remove(); inspector.insertBefore(renderTable(part), details);
      if(part.ai_review) {
        const review=part.ai_review, labels={ok:'ИИ не заметил явных расхождений',issues:'ИИ заметил возможные расхождения',uncertain:'ИИ не уверен в результате',failed:'Проверка ИИ недоступна',skipped:'Таблица не проверена ИИ'};
        const note=create('div','ai-review'); note.append(create('strong','',labels[review.status] || 'Проверка ИИ'));
        for(const issue of review.issues || []) note.append(create('p','',issue));
        if(review.reason) note.append(create('p','',review.reason));
        note.append(create('p','','Сверьте важные данные с оригиналом.')); inspector.insertBefore(note,details);
      }
    }
  }
  function renderTable(part) {
    const grid=create('table','recognized-table');
    for(let r=0;r<(part.rows || []).length;r++) {
      const row=create('tr');
      if(part.cells?.length) {
        for(const cell of part.cells.filter(c=>c.row===r).sort((a,b)=>a.column-b.column)) {
          const td=create(r===0&&!part.continuation_of_page?'th':'td','',cell.text);td.rowSpan=cell.row_span || 1;td.colSpan=cell.col_span || 1;
          td.title=`Строка ${r+1}, столбец ${cell.column+1}`;
          if(cell.requires_review) { td.classList.add('ai-cell'); td.title+=' · ИИ: сверьте с оригиналом'; td.append(create('small','ai-cell-label',' ИИ · проверить')); }
          for(const nested of cell.nested_tables || []) td.append(renderTable(nested));
          row.append(td);
        }
      } else for(const value of part.rows[r]) row.append(create(r===0&&!part.continuation_of_page?'th':'td','',String(value ?? '')));
      grid.append(row);
    }
    return grid;
  }
  function buttonFor(part, className) {
    const category=annotationCategory(part.kind), button=create('button',`${className} mark-${category}`);
    button.type='button'; button.dataset.category=category;
    button.title = `${annotationLabels[category]}: ${part.text || part.coordinate || part.name || ''}`;
    button.setAttribute('aria-label',button.title);
    button.onclick=()=>inspect(part,button);
    return button;
  }
  const pages = (native ? result.visual_layout.pages : result.document?.pages) || {};
  const isPdf = file.extension === '.pdf';
  const isImage = ['.png','.jpg','.jpeg','.webp','.tiff','.bmp'].includes(file.extension);
  if ((isPdf || isImage) && Object.keys(pages).length) {
    const note=create('p','annotation-note',native ? 'Геометрия документа и OCR. Заголовки и таблицы без границ определяются по признакам вёрстки; выбор области открывает данные.' : 'Блоки модели могут пересекаться и содержать ошибки классификации.'); root.append(note);
    let located = 0;
    for(const [number,page] of Object.entries(pages)) {
      scene.append(create('div','annotation-page-label',`Страница ${number}`));
      const canvas=create('div','annotation-page'); canvas.style.aspectRatio=`${page.size.width} / ${page.size.height}`;
      const image=create('img'); image.alt=`Страница ${number}`; image.loading='lazy';
      image.src=isPdf ? `${api}/${file.id}/pages/${number}` : `${api}/${file.id}/content`;
      image.onerror=()=> { image.alt='Не удалось загрузить изображение страницы'; };
      canvas.append(image);
      for(const part of parts) for(const prov of part.provenance || []) {
        if(String(prov.page_no)!==String(number) || !prov.bbox) continue;
        const rect=annotationRect(prov.bbox,page.size), button=buttonFor(part,'annotation-box');
        for(const [key,value] of Object.entries(rect)) button.style[key]=`${value}%`;
        button.append(create('span','box-label',annotationLabels[annotationCategory(part.kind)])); canvas.append(button); located++;
        const entry=create('button',`annotation-entry mark-${annotationCategory(part.kind)}`);
        entry.textContent=part.kind==='table' ? `${part.continuation_of_page ? `Продолжение таблицы со стр. ${part.continuation_of_page}` : 'Таблица'} · ${part.rows?.length || part.data?.num_rows || 0} строк` : part.text || part.kind; entry.title=entry.textContent;
        entry.onclick=()=>{inspect(part,button);button.scrollIntoView({block:'center',behavior:'smooth'});}; elementList.append(entry);
      }
      scene.append(canvas);
    }
    if (!located) scene.prepend(create('p','annotation-note','Координаты элементов отсутствуют. Ниже доступна структура.'));
    const unlocated=parts.filter(p=>!p.provenance?.length);
    if(unlocated.length) { scene.append(create('p','annotation-note',`${unlocated.length} элементов без координат`)); renderBlocks(unlocated); }
  } else {
    root.append(create('p','annotation-note','Структурное представление: расположение блоков может отличаться от оригинала.'));
    renderBlocks(parts);
  }
  function renderBlocks(items) {
    const book=create('div','annotation-blocks'); scene.append(book);
    let sheet=null, table=null;
    if(items.some(p=>p.kind==='sheet')) {
      for(const info of items.filter(p=>p.kind==='sheet')) {
        book.append(create('h3','',info.name));
        const cells=items.filter(p=>p.kind==='cell'&&p.sheet===info.name);
        if(!cells.length) {book.append(create('p','','Пустой лист'));continue;}
        let minR=Math.min(...cells.map(c=>c.row)),maxR=Math.max(...cells.map(c=>c.row)),minC=Math.min(...cells.map(c=>c.column)),maxC=Math.max(...cells.map(c=>c.column));
        const parse=address=>{const match=address.match(/^([A-Z]+)([0-9]+)$/);if(!match)return null;return [Number(match[2]),[...match[1]].reduce((n,ch)=>n*26+ch.charCodeAt(0)-64,0)];};
        const merges=(info.merged || []).map(range=>range.split(':').map(parse)).filter(pair=>pair.length===2&&pair.every(Boolean));
        for(const [a,b] of merges){minR=Math.min(minR,a[0]);maxR=Math.max(maxR,b[0]);minC=Math.min(minC,a[1]);maxC=Math.max(maxC,b[1]);}
        if((maxR-minR+1)*(maxC-minC+1)>10000) {book.append(create('p','','Лист слишком большой для сетки. Ячейки доступны во вкладке «Структура».'));continue;}
        const grid=create('table','annotated-sheet');const head=create('tr');head.append(create('th','',''));
        const columnLabel=n=>{let s='';while(n){n--;s=String.fromCharCode(65+n%26)+s;n=Math.floor(n/26);}return s;};
        for(let c=minC;c<=maxC;c++)head.append(create('th','',columnLabel(c)));grid.append(head);
        const values=new Map(cells.map(c=>[`${c.row}:${c.column}`,c]));
        for(let r=minR;r<=maxR;r++) {
          const row=create('tr');row.append(create('th','',String(r)));
          for(let c=minC;c<=maxC;c++) {
            const merge=merges.find(([a,b])=>a[0]<=r&&r<=b[0]&&a[1]<=c&&c<=b[1]);
            if(merge&&(merge[0][0]!==r||merge[0][1]!==c))continue;
            const td=create('td');if(merge){td.rowSpan=Math.min(maxR,merge[1][0])-r+1;td.colSpan=Math.min(maxC,merge[1][1])-c+1;}
            const cell=values.get(`${r}:${c}`);
            if(cell){const button=buttonFor(cell,'annotation-block');button.textContent=(cell.formula?'ƒ ':'')+String(cell.display_value??cell.value??'');button.title=`${cell.coordinate}: ${cell.value}${cell.calculation_status==='missing_cached_result'?' · Нет сохранённого результата формулы':''}`;td.append(button);}
            row.append(td);
          }
          grid.append(row);
        }
        book.append(grid);
      }
      return;
    }
    for(const part of items) {
      if(part.kind==='sheet') { sheet=part.name; book.append(create('h3','',sheet)); table=create('table','annotated-sheet'); book.append(table); continue; }
      if(part.kind==='cell') {
        if(!table || sheet!==part.sheet) { sheet=part.sheet; book.append(create('h3','',sheet)); table=create('table','annotated-sheet'); book.append(table); }
        const row=create('tr'), coordinate=create('th','',part.coordinate), value=create('td');
        const button=buttonFor(part,'annotation-block'); button.textContent=String(part.value ?? ''); value.append(button); row.append(coordinate,value); table.append(row); continue;
      }
      const button=buttonFor(part,'annotation-block');
      button.append(create('small','block-kind',part.kind));
      if(part.rows) {
        button.append(renderTable(part));
      } else if(part.data?.table_cells) {
        const grid=create('table'), rows=new Map();
        for(const cell of part.data.table_cells) { const index=cell.start_row_offset_idx; if(!rows.has(index)) rows.set(index,[]); rows.get(index).push(cell); }
        for(const [index,cells] of [...rows].sort((a,b)=>a[0]-b[0])) { const row=create('tr'); for(const cell of cells.sort((a,b)=>a.start_col_offset_idx-b.start_col_offset_idx)) row.append(create('td','',cell.text)); grid.append(row); } button.append(grid);
      } else button.append(create('div','',part.text || part.name || part.notes || 'Элемент без текста'));
      book.append(button);
    }
  }
  workspace.append(scene,side); root.append(legend,workspace); host.append(root);
}
