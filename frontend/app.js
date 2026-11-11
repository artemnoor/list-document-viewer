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
  for (const [label, mode] of [['Документ', 'original'], ['Разметка', 'annotations'], ['Структура', 'structure'], ['Markdown', 'markdown'], ['Текст', 'text'], ['JSON', 'json']]) {
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
      const toggle=document.createElement('button'); toggle.textContent='Показать исходник'; tools.append(toggle);
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
      toggle.onclick=()=>{source.hidden=!source.hidden;article.hidden=!source.hidden;toggle.textContent=source.hidden?'Показать исходник':'Предпросмотр';};
      panel.append(tools,article,source); output.append(panel); return;
    }
    if (mode === 'annotations') {
      renderAnnotations(output, result, file, API);
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
        const notices=[...(result.stale ? ['Сохранён результат предыдущей версии. Нажмите «Повторить обработку», чтобы применить новый OCR и исправления.'] : []),...(result.warnings || [])];
        if(notices.length) for(const notice of notices){const p=document.createElement('p');p.textContent=notice;status.append(p);}
        else status.textContent='Обработка завершена';
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
