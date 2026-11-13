const API = 'http://127.0.0.1:18765/api/documents';
const input = document.querySelector('#file-input'), list = document.querySelector('#file-list'), viewer = document.querySelector('#viewer'), zone = document.querySelector('#drop-zone');
const title = document.querySelector('#preview-title'), meta = document.querySelector('#preview-meta');
let files = [], selected = null, request = 0;
let viewGeneration = 0;
const emptyViewer = viewer.innerHTML;
const escapeHTML = value => value.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sizeLabel = bytes => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
function renderList() {
  document.querySelector('#count').textContent = files.length;
  document.querySelector('#list-count').textContent = files.length;
  list.innerHTML = files.length ? files.map(f => `<div class="file-entry"><button class="file-row ${f.id === selected ? 'active' : ''}" data-id="${f.id}"><span class="file-icon">▤</span><span class="file-info"><strong>${escapeHTML(f.name)}</strong><small>${escapeHTML((f.extension || 'ФАЙЛ').replace('.', '').toUpperCase())} · ${sizeLabel(f.size)}</small></span></button><button class="delete-file" data-delete="${f.id}" aria-label="Удалить ${escapeHTML(f.name)}" title="Удалить">×</button></div>`).join('') : '<p class="empty-list">Здесь появятся ваши документы</p>';
}
async function selectFile(file) {
  selected = file.id; localStorage.setItem('selected-document', file.id); const current = ++request; renderList(); title.textContent = file.name; meta.textContent = sizeLabel(file.size); viewer.innerHTML = '<div class="message">Открываем документ…</div>';
  try {
    const response = await fetch(`${API}/${file.id}`), data = await response.json();
    if (!response.ok) throw new Error(data.error);
    if (current !== request) return;
    if (data.type === 'pdf') viewer.innerHTML = `<iframe title="Предпросмотр PDF" src="${API}/${file.id}/content"></iframe>`;
    else if (data.type === 'image') viewer.innerHTML = `<div class="image-wrap"><img alt="${escapeHTML(file.name)}" src="${API}/${file.id}/content"></div>`;
    else if (data.type === 'structured') viewer.innerHTML = '<div class="message">Структурированный просмотр доступен во вкладке «Разметка».</div>';
    else { const pre = document.createElement('pre'); pre.className = 'document-text'; pre.textContent = data.text || 'Документ пуст'; viewer.replaceChildren(pre); }
  } catch (error) { if (current === request) viewer.innerHTML = `<div class="message"><strong>Не удалось открыть документ</strong><p>${escapeHTML(error.message)}</p></div>`; }
}
async function upload(items) {
  for (const file of items) {
    try {
      const response = await fetch(API, {method:'POST', headers:{'Content-Type':'application/octet-stream', 'X-File-Name':encodeURIComponent(file.name)}, body:file});
      const data = await response.json(); if (!response.ok) throw new Error(data.error);
      if (!files.some(file => file.id === data.id)) files.push(data);
      renderList(); selectFile(data);
    } catch(error) { alert(`${file.name}: ${error.message === 'Failed to fetch' ? 'Не удалось подключиться к серверу' : error.message}`); }
  }
}
input.addEventListener('change', () => { upload(Array.from(input.files)); input.value = ''; });
list.addEventListener('click', async event => {
  const remove = event.target.closest('[data-delete]');
  if (remove) {
    const file = files.find(f => f.id === remove.dataset.delete);
    if (!file || !confirm(`Удалить «${file.name}»?`)) return;
    remove.disabled = true;
    try {
      const response = await fetch(`${API}/${file.id}`, {method:'DELETE'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      files = files.filter(f => f.id !== file.id);
      if (selected === file.id) {
        selected = null; ++request; ++viewGeneration; localStorage.removeItem('selected-document');
        if (files.length) selectFile(files[0]);
        else { title.textContent = 'Просмотр документа'; meta.textContent = 'Файл не выбран'; viewer.innerHTML = emptyViewer; }
      }
      renderList();
    } catch (error) { alert('Не удалось удалить файл: ' + error.message); remove.disabled = false; }
    return;
  }
  const row = event.target.closest('[data-id]'); if (row) selectFile(files.find(f => f.id === row.dataset.id));
});
for (const name of ['dragenter','dragover']) zone.addEventListener(name, e => { e.preventDefault(); zone.classList.add('dragging'); });
for (const name of ['dragleave','drop']) zone.addEventListener(name, e => { e.preventDefault(); zone.classList.remove('dragging'); });
zone.addEventListener('drop', e => upload(Array.from(e.dataTransfer.files)));

// Structured analysis is asynchronous; switching documents cancels polling.
const originalSelect = selectFile;
selectFile = async function(file) {
  const generation = ++viewGeneration;
  await originalSelect(file);
  if (generation !== viewGeneration || selected !== file.id) return;
  const content = document.createElement('div');
  content.className = 'original-preview';
  while (viewer.firstChild) content.append(viewer.firstChild);
  const shell = document.createElement('div'); shell.className = 'analysis-shell';
  const toolbar = document.createElement('div'); toolbar.className = 'analysis-toolbar';
  const output = document.createElement('div'); output.className = 'analysis-output'; output.textContent = 'Ожидает обработки…';
  for (const [label, mode] of [['Документ', 'original'], ['Разметка', 'annotations'], ['ИИ-проверка', 'document_review'], ['Структура', 'structure'], ['Markdown', 'markdown'], ['Текст', 'text'], ['JSON', 'json']]) {
    const button = document.createElement('button'); button.textContent = label;
    button.setAttribute('aria-selected', String(mode === 'original'));
    button.onclick = () => { for(const tab of toolbar.querySelectorAll('[aria-selected]')) tab.setAttribute('aria-selected','false'); button.setAttribute('aria-selected','true'); content.hidden = mode !== 'original'; output.hidden = mode === 'original'; shell.dataset.mode = mode; draw(); };
    toolbar.append(button);
  }
  const download = document.createElement('button'); download.textContent = 'Скачать JSON'; download.disabled = true; toolbar.append(download);
  const downloadMd = document.createElement('button'); downloadMd.textContent = 'Скачать .md'; downloadMd.disabled = true; toolbar.append(downloadMd);
  const retry = document.createElement('button'); retry.textContent = 'Повторить обработку'; retry.disabled = true; toolbar.append(retry);
  retry.onclick = async () => {
    retry.disabled=true;
    try {
      const response=await fetch(`${API}/${file.id}/retry`,{method:'POST'});
      const data=await response.json();if(!response.ok)throw Error(data.error);
      if(generation===viewGeneration) selectFile(file);
    } catch(error) { status.textContent='Не удалось повторить обработку: '+error.message;retry.disabled=false; }
  };
  const status=document.createElement('div');status.className='analysis-status';status.setAttribute('role','status');status.textContent='Проверяем сохранённый результат…';
  shell.append(toolbar, status, content, output); viewer.replaceChildren(shell); output.hidden = true;
  let result = null;
  function draw() {
    if (!result) return;
    output.replaceChildren();
    const mode = shell.dataset.mode;
    if (mode === 'markdown') {
      const panel=document.createElement('div'); panel.className='markdown-panel';
      const tools=document.createElement('div'); tools.className='markdown-tools';
      const status=document.createElement('span'); status.textContent='Markdown · UTF-8'; tools.append(status);
      const toggle=document.createElement('button'); toggle.textContent='Показать Markdown-текст'; tools.append(toggle);
      const article=document.createElement('article'); article.className='markdown-preview';
      const source=document.createElement('pre'); source.className='markdown-source'; source.textContent=result.export_markdown ?? result.markdown; source.hidden=true;
      if(result.markdown_preview) article.innerHTML=result.markdown_preview;
      else article.textContent=result.export_markdown || result.markdown || 'В документе нет распознанного текста.';
      for(const table of article.querySelectorAll('table')) {
        for(const cell of table.querySelectorAll('td')) {
          if(/^[\s\d.,%()₽$€+−-]+$/.test(cell.textContent) && /\d/.test(cell.textContent)) cell.classList.add('numeric-cell');
        }
        if(table.closest('td,th')) continue;
        const scroll=document.createElement('div');scroll.className='markdown-table-scroll';scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label','Таблица, прокрутка по горизонтали');table.before(scroll);scroll.append(table);
      }
      toggle.onclick=()=>{source.hidden=!source.hidden;article.hidden=!source.hidden;toggle.textContent=source.hidden?'Показать Markdown-текст':'Предпросмотр';};
      panel.append(tools,article,source); output.append(panel); return;
    }
    if (mode === 'annotations') {
      renderAnnotations(output, result, file, API);
      return;
    }
    if (mode === 'document_review') {
      renderDocumentReview(output, result, file, API, updated => {
        result = updated;
        status.replaceChildren();
        const summary = document.createElement('p');
        summary.textContent = result.quality?.status === 'needs_review' ? 'В результате остались замечания для проверки.' : 'Решение сохранено.';
        status.append(summary);
        for (const reason of result.quality?.reasons || []) { const item=document.createElement('p');item.textContent=reason;status.append(item); }
        draw();
      });
      return;
    }
    if (mode === 'text' || mode === 'json') {
      const pre = document.createElement('pre'); pre.textContent = mode === 'text' ? result.markdown : JSON.stringify(result, null, 2); output.append(pre); return;
    }
    const summary = document.createElement('p'); summary.textContent = `${result.parts.length} элементов · ${result.chunks.length} фрагментов`; output.append(summary);
    for (const warning of result.warnings) { const p = document.createElement('p'); p.textContent = warning; output.append(p); }
    for (const part of result.parts) {
      const details = document.createElement('details'), caption = document.createElement('summary'), pre = document.createElement('pre');
      caption.textContent = [part.kind, part.sheet, part.coordinate, part.name, part.page ? `Страница ${part.page}` : '', part.text?.slice(0, 90)].filter(Boolean).join(' · ');
      pre.textContent = JSON.stringify(part, null, 2); details.append(caption, pre); output.append(details);
    }
  }
  while (generation === viewGeneration && selected === file.id && shell.isConnected) {
    try {
      const response = await fetch(`${API}/${file.id}/analysis`); const data = await response.json();
      if(generation !== viewGeneration || !shell.isConnected) return;
      if (!response.ok) throw new Error(data.error || 'Ошибка анализа');
      if (data.state === 'error') throw new Error(data.error);
      if (data.state === 'ready') {
        result = data.result; download.disabled = false;
        retry.disabled = false;
        status.replaceChildren();
        const processingNotice = result.processing_status === 'partial' ? 'Обработка завершилась частично.' : result.processing_status === 'failed' ? 'Обработка завершилась с ошибкой.' : 'Обработка завершена.';
        const qualityNotice = result.quality?.status === 'not_available' ? 'Оценка качества недоступна.' : result.quality?.status === 'needs_review' ? 'Распознавание требует проверки: ' + result.quality.reasons.join(' ') : result.quality?.status === 'passed' ? 'Проверка качества пройдена.' : 'Качество распознавания не подтверждено. Сверьте важные данные с оригиналом.';
        const notices=[processingNotice,qualityNotice, ...(result.stale ? ['Сохранён результат предыдущей версии. Нажмите «Повторить обработку», чтобы применить новый OCR и исправления.'] : []),...(result.warnings || [])];
        for(const notice of notices){const p=document.createElement('p');p.textContent=notice;status.append(p);}
        downloadMd.disabled = !(result.export_markdown || result.markdown || '').trim();
        downloadMd.onclick = () => { const url=URL.createObjectURL(new Blob([result.export_markdown ?? result.markdown],{type:'text/markdown;charset=utf-8'})); const a=document.createElement('a');a.href=url;a.download=file.name.replace(/\.[^.]+$/, '')+'.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000); };
        download.onclick = () => { const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type:'application/json'})); const a = document.createElement('a'); a.href = url; a.download = file.name + '.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
        if (!shell.dataset.mode && ['.xlsx','.xlsm','.pptx'].includes(file.extension)) {
          [...toolbar.querySelectorAll('button')].find(button=>button.textContent==='Разметка')?.click();
        }
        draw(); break;
      }
      output.textContent = data.state === 'queued' ? 'В очереди…' : 'Распознаём структуру документа…';
      status.textContent=output.textContent;
    } catch(error) { output.textContent = 'Ошибка обработки: ' + error.message;status.textContent=output.textContent;retry.disabled=false;break; }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
};

function renderDocumentReview(host, result, file, api, onUpdate) {
  const create = (tag, className, text) => { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined) el.textContent = text; return el; };
  const review = result.document_review || {status:result.stale ? 'outdated' : 'disabled', suggestions:[]};
  const summary = create('section','document-review-summary');
  summary.append(create('h2','','Повторное чтение документа'));
  summary.append(create('p','',`Модель: ${review.model || 'DeepSeek V4.1 Flash'}. Проверено страниц: ${review.pages_checked || 0} из ${review.pages_total || 0}.`));
  if (review.cost_rub !== null && review.cost_rub !== undefined) summary.append(create('p','','Стоимость по данным Polza: ' + review.cost_rub + ' ₽.'));
  const state = {
    disabled:'Проверка выключена или не настроен ключ Polza.',
    complete:'Модель прочитала доступные страницы и подготовила предложения для ручной проверки.',
    partial:'Часть страниц не удалось проверить. Результат сохранён, проверьте статус каждой страницы.',
    failed:'Не удалось завершить повторную проверку документа.',
    no_pages:'В документе нет страниц для проверки.',
    outdated:'Для сохранённого результата нужно нажать «Повторить обработку», чтобы запустить новый проход.'
  };
  summary.append(create('p','document-review-state',state[review.status] || review.error || 'Статус проверки неизвестен.'));
  const failedPages = (review.pages || []).filter(page => page.status === 'failed').map(page => page.page_no);
  if (failedPages.length) summary.append(create('p','document-review-error','Не обработаны страницы: ' + failedPages.join(', ') + '.'));
  const partialPages = (review.pages || []).filter(page => page.status === 'partial').map(page => page.page_no);
  if (partialPages.length) summary.append(create('p','document-review-error','Результат распознавания сокращён на страницах: ' + partialPages.join(', ') + '.'));
  if (review.error) summary.append(create('p','document-review-error',review.error));
  if (review.last_batch_accept) {
    const batch = review.last_batch_accept;
    summary.append(create('p', batch.skipped ? 'document-review-error' : 'document-review-state',
      `Принято предложений: ${batch.accepted}. Не удалось применить: ${batch.skipped}.`));
  }
  host.append(summary);

  const suggestions = review.suggestions || [];
  const pendingSuggestions = suggestions.filter(suggestion => suggestion.status === 'pending');
  if (pendingSuggestions.length) {
    const batchActions = create('div','document-review-actions');
    const acceptAll = create('button','','Принять все изменения (' + pendingSuggestions.length + ')');
    const batchNote = create('p','document-review-error','');
    acceptAll.onclick = async () => {
      acceptAll.disabled = true;
      batchNote.textContent = '';
      try {
        const response = await fetch(`${api}/${file.id}/document-review/accept-all`,
          {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Не удалось принять предложения');
        onUpdate(data.result);
      } catch (error) {
        batchNote.textContent = error.message;
        acceptAll.disabled = false;
      }
    };
    batchActions.append(acceptAll);
    host.append(batchActions,batchNote);
  }
  if (!suggestions.length) {
    host.append(create('p','document-review-empty',review.status === 'complete' ? 'Явных расхождений модель не предложила. Это не подтверждает точность результата.' : 'Предложений пока нет.'));
    return;
  }
  for (const suggestion of suggestions) {
    const card = create('article','document-review-card');
    const actionNames = {replace_text:'Исправить текст',replace_cell:'Исправить ячейку таблицы',add_text:'Добавить пропущенный текст',add_table_row:'Добавить строку таблицы',add_table:'Добавить пропущенную таблицу'};
    const heading = create('h3','',`${actionNames[suggestion.action] || 'Предложение ИИ'} · страница ${suggestion.page_no}`);
    card.append(heading);
    if (suggestion.action === 'replace_cell') card.append(create('p','document-review-target',`Строка ${Number(suggestion.row)+1}, столбец ${Number(suggestion.column)+1}`));
    if (suggestion.action === 'add_table_row') card.append(create('p','document-review-target',`Добавить после строки ${Number(suggestion.row)+1}`));
    if (['add_text','add_table_row','add_table'].includes(suggestion.action) && suggestion.bbox_normalized) {
      card.append(create('p','document-review-target','Место пропуска отмечено на исходной странице и появится в разметке после принятия.'));
    }
    const values = create('div','document-review-values');
    if (!['add_text','add_table_row','add_table'].includes(suggestion.action)) {
      const originalBox=create('div','document-review-value');originalBox.append(create('span','','Распознано:'),create('pre','document-review-original',String(suggestion.original ?? '')));values.append(originalBox);
    }
    const proposedBox=create('div','document-review-value');proposedBox.append(create('span','', ['add_table_row','add_table'].includes(suggestion.action) ? 'Предложенная структура (JSON):' : 'Предлагаемое изменение:'));
    const editor = create('textarea','document-review-proposed',Array.isArray(suggestion.proposed) ? JSON.stringify(suggestion.proposed, null, 2) : String(suggestion.proposed ?? ''));
    editor.setAttribute('aria-label','Предлагаемое изменение');
    editor.rows = Array.isArray(suggestion.proposed) ? Math.min(8, suggestion.proposed.length + 2) : Math.min(8, Math.max(3, String(suggestion.proposed ?? '').split('\n').length + 1));
    if (suggestion.status !== 'pending') editor.disabled = true;
    proposedBox.append(editor);values.append(proposedBox);card.append(values);
    if (suggestion.reason) card.append(create('p','document-review-reason','Замечание модели: ' + suggestion.reason));
    if (suggestion.evidence) card.append(create('p','document-review-evidence','Фрагмент по версии модели: ' + suggestion.evidence));
    const source = create('a','document-review-source','Открыть исходник');
    source.target = '_blank'; source.rel = 'noopener';
    source.href = file.extension === '.pdf' ? `${api}/${file.id}/pages/${suggestion.page_no}` :
      ['.png','.jpg','.jpeg','.tiff','.tif','.bmp','.webp'].includes(file.extension) ? `${api}/${file.id}/content` : `${api}/${file.id}`;
    card.append(source);
    if (suggestion.status === 'accepted') {
      card.append(create('p','document-review-decision','Изменение принято пользователем.'));
      const undo = create('button','','Отменить изменение');
      const note = create('p','document-review-error','');
      undo.onclick = async () => {
        undo.disabled = true;
        try {
          const response = await fetch(`${api}/${file.id}/document-review/${suggestion.id}/undo`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Не удалось отменить изменение');
          onUpdate(data.result);
        } catch (error) { note.textContent = error.message; undo.disabled = false; }
      };
      card.append(undo,note);
    }
    else if (suggestion.status === 'rejected') card.append(create('p','document-review-decision','Предложение отклонено.'));
    else if (suggestion.status === 'undone') card.append(create('p','document-review-decision','Изменение отменено; его исходное распознавание восстановлено.'));
    else if (suggestion.status === 'verification_failed') card.append(create('p','document-review-error',suggestion.verification_note || 'Повторная проверка по оригиналу не подтвердила предложение. Оно не применено.'));
    else {
      const actions = create('div','document-review-actions');
      const accept = create('button','','Принять изменение');
      const reject = create('button','','Отклонить');
      const note = create('p','document-review-error','');
      accept.onclick = async () => {
        accept.disabled = reject.disabled = true;
        let proposed = editor.value;
        if (['add_table_row','add_table'].includes(suggestion.action)) {
          try { proposed = JSON.parse(proposed); }
          catch { note.textContent = 'Для таблицы укажите корректный JSON-массив.'; accept.disabled = reject.disabled = false; return; }
        }
        try {
          const response = await fetch(`${api}/${file.id}/document-review/${suggestion.id}/accept`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proposed})});
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Не удалось принять предложение');
          onUpdate(data.result);
        } catch (error) { note.textContent = error.message; accept.disabled = reject.disabled = false; }
      };
      reject.onclick = async () => {
        accept.disabled = reject.disabled = true;
        try {
          const response = await fetch(`${api}/${file.id}/document-review/${suggestion.id}/reject`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
          const data = await response.json();
          if (!response.ok) throw new Error(data.error || 'Не удалось отклонить предложение');
          onUpdate(data.result);
        } catch (error) { note.textContent = error.message; accept.disabled = reject.disabled = false; }
      };
      actions.append(accept,reject); card.append(actions,note);
    }
    host.append(card);
  }
}

async function restoreDocuments() {
  try {
    const response = await fetch(API);
    if (!response.ok) throw new Error('Не удалось восстановить документы');
    const data = await response.json();
    for (const file of data.documents) if (!files.some(existing => existing.id === file.id)) files.push(file);
    renderList();
    if (!selected && files.length) selectFile(files.find(file => file.id === localStorage.getItem('selected-document')) || files[0]);
  } catch (error) {
    document.querySelector('.empty-list')?.replaceChildren(document.createTextNode('Сервер недоступен. Обновите страницу после запуска API.'));
  }
}
restoreDocuments();
