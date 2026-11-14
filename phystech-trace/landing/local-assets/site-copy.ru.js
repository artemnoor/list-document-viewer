(function () {
  'use strict';

  var $ = function (selector, root) { return Array.from((root || document).querySelectorAll(selector)); };
  var set = function (selector, value, index, root) {
    var nodes = $(selector, root);
    var node = nodes[index || 0];
    if (node) node.textContent = value;
    return node;
  };
  var setMany = function (selector, values, root, hideRemainder) {
    var nodes = $(selector, root);
    values.forEach(function (value, i) { if (nodes[i]) nodes[i].textContent = value; });
    if (hideRemainder) nodes.slice(values.length).forEach(function (node) { node.hidden = true; node.style.display = 'none'; });
    return nodes;
  };
  var hide = function (selector, root) { $(selector, root).forEach(function (node) { node.hidden = true; node.style.display = 'none'; }); };
  var page = location.pathname.replace(/\/$/, '') || '/';

  function shared() {
    setMany('.nav-links .nav-text', ['Сравнение', 'Сравнение', 'Блог', 'Блог', 'Кейсы', 'Кейсы', 'О платформе', 'О платформе', 'Войти', 'Войти']);
    $('.nav-links .cta').forEach(function (link) {
      link.setAttribute('href', '/register');
      var labels = link.querySelectorAll('.nav-text');
      if (labels.length) labels.forEach(function (label) { label.textContent = 'Зарегистрироваться'; });
      else link.textContent = 'Зарегистрироваться';
    });
    $('a.nav-link-block.login, a[href="https://portal.transform9.com/"]').forEach(function (link) { link.setAttribute('href', '/logIn'); });
    $('a[href="/book-a-demo"], a[href="/book-a-demo/"]').forEach(function (link) { link.setAttribute('href', '/register'); });
    setMany('.footer-link', ['Домой', 'Сравнение', 'Блог', 'Кейсы', 'Контакты', 'Документация', 'Документация', 'Документация', 'Связаться с нами', 'Зарегистрироваться', 'Связаться с нами']);
    set('.footer-transp.left', 'Интеллектуальная проверка отчётности. От распознавания документов до обоснованного заключения.');
    setMany('.footer-transp:not(.left):not(.bottom)', ['Навигация', 'Интеграция', 'Социальные сети', 'Контакты', 'Контакты', 'Будьте в курсе']);
    set('.footer-transp.bottom', '© 2026 Phystech Trace. Все права защищены.');
    setMany('.footer-transp.bottom-links', ['Политика конфиденциальности', 'Условия использования'], document, true);
    setMany('.cta-section .cta-bottom', ['Документы', 'Анализ', 'Извлечение', 'Сопоставление', 'Проверка', 'Быстрый старт', 'Зарегистрироваться']);
    setMany('.cta-section .footer-cta', ['Зарегистрироваться', 'Зарегистрироваться']);
    set('.cta-section .bottom-cta-right', 'Посмотреть, как это работает');
    set('.cta-section h2.cta-bottom', 'От документов к обоснованным решениям.');
    var shareNames = { x: 'X', facebook: 'Facebook', linkedin: 'LinkedIn' };
    $('a[fs-socialshare-element]').forEach(function (link) {
      var service = shareNames[link.getAttribute('fs-socialshare-element')];
      if (!service) return;
      link.setAttribute('aria-label', 'Поделиться в ' + service);
      link.querySelectorAll('img').forEach(function (icon) { icon.alt = ''; });
    });
  }

  function home() {
    hide('.testimonials,.how-it-works,.cta-section .cta-top-text-list');
    if (document.querySelector('.split-cards-section .split-cards-right-wrap') && !document.getElementById('compact-home-cards')) {
      var compactHomeCards = document.createElement('style');
      compactHomeCards.id = 'compact-home-cards';
      compactHomeCards.textContent = '@media (min-width: 992px) { .split-cards-section .split-cards-right-wrap { row-gap: 4px; grid-row-gap: 4px; } .stacking-cards-section.schudule-agent .scheduling-cards { height: auto; row-gap: 4px; grid-row-gap: 4px; } }';
      document.head.appendChild(compactHomeCards);
    }
    var hero = document.querySelector('.hero.home');
    if (hero) {
      var title = hero.querySelector('h1.hero-home');
      if (title) {
        title.innerHTML = 'Проверка <span class="head-span-3">достоверности отчётности</span><br>на основе первичных учётных документов';
      }
      set('._16px-text.white-text', 'О платформе:', 0, hero);
      set('.home-hero-text', 'Phystech Trace анализирует первичные документы, сверяет показатели и показывает источник каждого вывода.', 0, hero);
      document.querySelectorAll('h2.hero-home').forEach(function (oldHeading) { oldHeading.hidden = true; oldHeading.style.display = 'none'; });
    }

    var stats = document.querySelector('.stats');
    if (stats) {
      set('.stats-text', 'Результат, который можно проверить', 0, stats);
      set('.stats-span', 'От загрузки документов до обоснованного заключения. Каждый этап анализа сохраняет связь с исходными материалами.', 0, stats);
      setMany('.stat-head', ['Распознавание', 'Извлечение данных', 'Связь документов', 'Проверка достоверности'], stats);
      setMany('.stat-descr', [
        'Анализ структуры, содержания и визуальных элементов документов.',
        'Определение и извлечение показателей с учётом контекста.',
        'Связь отчётности с первичными и подтверждающими документами.',
        'Выявление расхождений и формирование доказательной базы.'
      ], stats);
    }

    var testimonials = document.querySelector('.testimonials');
    if (testimonials) {
      set('.testim-heading', 'Прозрачность на каждом этапе проверки', 0, testimonials);
      setMany('._16px-text', ['Избранное', 'Прозрачность'], testimonials, false);
      var quotes = $('.testimonial', testimonials);
      if (quotes[0]) quotes[0].textContent = 'Не просто результат работы искусственного интеллекта — понятное обоснование каждого вывода с возможностью перейти к исходному документу.';
      quotes.slice(1).forEach(function (node) { node.hidden = true; });
      hide('.testim-name,.testim-highlight,.testim-job,.testim-num,.testim-point,.slider-current,.slider-all', testimonials);
      testimonials.querySelectorAll('._16px-text').forEach(function (node, i) { if (i > 1) node.hidden = true; });
    }

    var how = document.querySelector('.how-it-works');
    if (how) {
      set('._16px-text.white-text', 'Как это работает', 0, how);
      setMany('.hiw-text.left', ['Анализ', 'Анализ'], how);
      set('.hiw-text._1', 'Извлечение', 0, how);
      set('.hiw-text._2', 'Сопоставление', 0, how);
      set('.hiw-text._3', 'Проверка', 0, how);
      set('.hiw-bottom', 'От загрузки документов до обоснованного заключения. Каждый этап анализа сохраняет связь с исходными материалами. Система исследует структуру и содержание документов, определяет значимые сведения и устанавливает связи между источниками.', 0, how);
    }

    var products = document.querySelector('.white-section');
    if (products) {
      set('._16px-text', 'Наши возможности', 0, products);
      setMany('h2.agent', [
        'Интеллектуальная обработка документов', 'Анализ документов', 'Для каких задач создана платформа', 'Создано для работы с разными документами'
      ], products);
      setMany('.stack-card-head', ['Распознавание и анализ структуры', 'Определение типа документа', 'Структурированное извлечение данных', 'Проверка и подтверждение данных'], products);
      setMany('.stack-card-text', [
        'Обрабатывайте электронные документы и сканированные материалы, сохраняя структуру страниц, таблиц, текстовых блоков и других элементов.',
        'ИИ анализирует содержание и контекст файла, определяет его назначение и выбирает подход к дальнейшей обработке.',
        'Извлекайте показатели, реквизиты, суммы, даты и другие сведения с сохранением контекста и происхождения.',
        'Связывайте показатели с исходными документами, сопоставляйте значения и выявляйте несоответствия.'
      ], products);
      setMany('.task-text-row', ['Выявление расхождений', 'Связи между документами', 'Подтверждение показателей', 'Формирование заключения'], products);
      setMany('.task-text', [
        'Определение характера расхождений и формирование доказательной базы.',
        'Установление взаимосвязей между отчётностью, первичными документами и подтверждающими материалами.',
        'Переход от каждого результата проверки к исходному документу.'
      ], products);
      setMany('._30px-text.black', ['Выявление расхождений', 'Связи между документами', 'Подтверждение показателей'], products);
      setMany('.row-tab-head', ['Проверка финансовой отчётности', 'Внутренний финансовый контроль', 'Проверка первичных документов', 'Сверка расчётов и показателей'], products);
      setMany('.row-tab-text', [
        'Проверяйте отчёты по первичным учётным документам.',
        'Анализируйте комплекты документации в рамках единого процесса.',
        'Выявляйте несоответствия между показателями и источниками.',
        'Формируйте доказательную базу и рекомендации.'
      ], products);
      set('.out-left-bottom', 'Отдельные документы и целые комплекты материалов — система анализирует каждый файл в контексте общей задачи проверки.', 0, products);
      setMany('.out-card-text-bottom', ['Отчёты', 'Счета', 'Акты', 'Накладные', 'УПД', 'Договоры', 'Платёжные документы', 'Банковские выписки', 'И другие виды документации.'], products);
      setMany('.out-card ._30px-text.white', ['Отчёты', 'Счета', 'Акты', 'Накладные', 'УПД'], products);
      products.querySelectorAll('._16px-text').forEach(function (node) { if (/^#\d+$/.test(node.textContent.trim())) node.hidden = true; });
    }

    var specialty = document.querySelector('.specialty-section');
    if (specialty) {
      set('._16px-text.white-text.specialty', 'Для каких задач создана платформа', 0, specialty);
      set('.text-span-13', '', 0, specialty);
      setMany('._30px-text', [
        'Проверка финансовой отчётности', 'Внутренний финансовый контроль', 'Проверка первичных учётных документов',
        'Сверка расчётов и показателей', 'Анализ комплектов документации', 'Выявление несоответствий в отчётах',
        'Подготовка материалов для аудита', 'Контроль достоверности данных'
      ], specialty, true);
      specialty.querySelectorAll('.specialty-tab-link').forEach(function (tab) {
        var label = tab.querySelector('._30px-text');
        if (!label || label.hidden || !label.textContent.trim()) tab.remove();
      });
      specialty.querySelectorAll('.specialty-tab-pane').forEach(function (pane, index) {
        if (index >= 8) pane.remove();
      });
    }

    var integration = document.querySelector('.integration-section');
    if (integration) {
      set('.integration-head', 'Подключайте Phystech Trace к существующим процессам', 0, integration);
      set('.integration', 'Платформа проектируется как модульная система, которую можно адаптировать под особенности документооборота организации, используемые форматы и требования к проверке.', 0, integration);
      hide('.integration-top-right-wrap ._30px-text', integration);

      var formats = [
        { label: 'PDF', icon: 'pdf.svg' },
        { label: 'DOC / DOCX', icon: 'docx.svg' },
        { label: 'XLS / XLSX', icon: 'xlsx.svg' },
        { label: 'PPTX', icon: 'pptx.svg' },
        { label: 'CSV', icon: 'csv.svg' },
        { label: 'JPG / PNG', icon: 'photo.svg' }
      ];
      var tickerRows = $('.intagrations-row', integration);
      tickerRows.forEach(function (row) {
        var rowFormats = row.classList.contains('_2') ? formats.slice().reverse() : formats;
        row.replaceChildren();
        for (var repeat = 0; repeat < 2; repeat++) {
          rowFormats.forEach(function (format) {
            var item = document.createElement('div');
            item.className = 'integration-block bl format-file-block';
            item.setAttribute('aria-label', 'Формат файла ' + format.label);
            var icon = document.createElement('img');
            icon.className = 'format-file-icon';
            icon.src = '/local-assets/file-icons/' + format.icon;
            icon.alt = '';
            icon.loading = 'eager';
            var label = document.createElement('span');
            label.className = 'format-file-label';
            label.textContent = format.label;
            item.append(icon, label);
            row.appendChild(item);
          });
        }
      });
    }

    var secure = document.querySelector('.secure-section');
    if (secure) {
      set('.secure', 'Достоверность и прозрачность', 0, secure);
      set('.secure-head-span', '', 0, secure);
      set('.secure', 'Каждый вывод должен иметь основание. Phystech Trace сохраняет связь между результатами анализа и исходными документами. Это позволяет проследить происхождение показателей, проверить обнаруженные расхождения и оценить обоснованность итогового заключения.', 1, secure);
    }
  }

  function comparePage() {
    var hero = document.querySelector('.hero.home');
    set('.hero-home.compare', 'Сравнение решений | Найдите новый подход к проверке отчётности', 0, hero || document);
    set('._16px-text.white-text', 'О чём мы', 0, hero || document);
    set('.home-hero-text', 'Phystech Trace — интеллектуальная платформа для анализа и проверки отчётности по первичным учётным документам. Мы объединяем распознавание документов, понимание их содержания, извлечение данных и интеллектуальное сопоставление информации в едином процессе.', 0, hero || document);
    setMany('.footer-cta', ['Посмотреть демо', 'Зарегистрироваться']);

    var generic = document.querySelector('.generic-section');
    if (generic) {
      set('.why-text', 'Почему Phystech Trace', 0, generic);
      var genericTitle = generic.querySelector('h2.generic');
      if (genericTitle) genericTitle.textContent = 'Не просто OCR. Не просто чат с ИИ.';
      set('.generic-text', 'Большинство инструментов решают отдельные задачи: распознают текст, извлекают реквизиты или отвечают на вопросы по загруженным файлам. Phystech Trace объединяет эти возможности в единую систему, которая понимает контекст документов, устанавливает связи между ними и проверяет достоверность показателей с опорой на исходные материалы.', 0, generic);
      hide('.left-side.generic', generic);
    }

    var table = document.querySelector('.table-section');
    if (table) {
      set('.table-head', 'Сравнение', 0, table);
      set('.table-span', 'подходов', 0, table);
      set('p.table-head', 'Обычные AI-инструменты', 0, table);
      var cells = [
        'Обработка документов', 'Вручную', 'Автоматически',
        'Определение типа документа', 'Специалистом', 'С учётом содержания и контекста',
        'Извлечение данных', 'Вручную', 'Структурированное извлечение',
        'Связь документов', 'Вручную', 'Анализ взаимосвязей',
        'Сверка показателей', 'Вручную', 'В рамках единого процесса',
        'Выявление расхождений', 'Специалистом', 'Интеллектуальный анализ',
        'Подтверждение результатов', 'Исходными файлами', 'Связь с источниками',
        'Итоговое заключение', 'Вручную', 'Обоснованная рекомендация'
      ];
      setMany('.table-text', cells, table);
      $('.table-text', table).slice(24).forEach(function (node) { node.hidden = true; });
      set('.table-bottom-left-text', 'Распознать текст недостаточно. Phystech Trace анализирует контекст документов, устанавливает взаимосвязи и сопоставляет сведения из разных источников.', 0, table);
    }

    var access = document.querySelector('.access-section');
    if (access) {
      set('.access-top-label', 'Никаких догадок — только проверяемые результаты', 0, access);
      set('.access', 'Обычная обработка документов', 0, access);
      set('.access-span', 'не подтверждает выводы', 0, access);
      setMany('.access-block-head', ['Проблема обычной обработки документов', 'Интеллектуальный подход Phystech Trace'], access);
      setMany('.access-block-text', [
        'Распознать текст недостаточно. Даже корректно извлечённый показатель не становится подтверждённым, пока не установлена его связь с соответствующим первичным документом.',
        'ИИ анализирует документы в контексте общей задачи, определяет смысл показателей, устанавливает взаимосвязи и сопоставляет сведения из разных источников.'
      ], access);
    }

    var white = document.querySelector('.white-section');
    if (white) {
      set('.sp-label', 'Построено вокруг достоверности данных', 0, white);
      set('.sp-wh', 'Отдельные документы — единая система взаимосвязей', 0, white);
      set('.specialty-bottom', 'Phystech Trace рассматривает комплект документации как связанную информационную среду. Это помогает находить подтверждения, учитывать контекст и выявлять несоответствия, которые сложно обнаружить при изолированной обработке файлов.', 0, white);
      hide('.specialty-section', white);
    }

    var integration = document.querySelector('.integration-section');
    if (integration) {
      var controlTitle = integration.querySelector('h2');
      if (controlTitle) controlTitle.textContent = 'Контроль и прозрачность';
      set('.integration', 'Каждый результат проверки сопровождается доказательной базой. Специалист может изучить исходные материалы, проверить расхождения и оценить сформированную рекомендацию.', 0, integration);
    }

    var privacy = document.querySelector('.privacy-section');
    if (privacy) {
      set('h2.privacy', 'Каждый вывод должен иметь основание', 0, privacy);
      setMany('.privacy-head', ['Прослеживаемость показателей', 'Подтверждение результатов', 'Выявление расхождений', 'Обоснованное заключение'], privacy);
      setMany('.privacy-text', [
        'Phystech Trace сохраняет связь между результатами анализа и исходными документами.',
        'Можно проверить происхождение показателей и перейти к подтверждающим материалам.',
        'Система помогает оценить обнаруженные несоответствия и их основания.',
        'Результат проверки сопровождается прозрачной доказательной базой.'
      ], privacy);
    }

    var evaluation = document.querySelector('.ev-section');
    if (evaluation) {
      set('.ev-label', 'Для кого создан Phystech Trace', 0, evaluation);
      setMany('.ev', ['Финансовые подразделения', 'и бухгалтерские службы'], evaluation);
      setMany('.ev-head', ['Внутренний контроль и аудит', 'Финансовые организации', 'Компании с большим документооборотом', 'Бухгалтерские службы'], evaluation);
      setMany('.ev-tab-text', [
        'Проверяйте отчётность по первичным учётным документам.',
        'Анализируйте комплекты документации в рамках единого процесса.',
        'Подтверждайте показатели ссылками на исходные материалы.',
        'Находите расхождения и получайте обоснованные результаты.'
      ], evaluation);
    }
  }

  function blogPage() {
    var hero = document.querySelector('.hero.blog');
    if (hero) {
      var title = hero.querySelector('h1');
      if (title) title.textContent = 'Phystech Trace Blog: технологии интеллектуальной обработки документов';
      set('.featured-head', 'Почему одного OCR недостаточно для проверки финансовой отчётности', 0, hero);
      set('.blog-point', 'Phystech Trace', 0, hero);
      set('.blog-point', 'Рекомендуемые материалы', 1, hero);
    }
    var section = document.querySelector('.all-blogs-section');
    if (section) {
      set('._56-px-text.white.right-side-heading', 'Рекомендуемые материалы', 0, section);
      set('._16px-text.white-text', 'Мысли и исследования', 0, section);
      var titles = $('.blog-title', section);
      var articleTitles = [
        'Почему одного OCR недостаточно для проверки финансовой отчётности',
        'Как ИИ устанавливает связи между первичными документами',
        'Как находить расхождения в финансовой документации'
      ];
      var excerpts = [
        'Распознавание текста — только первый этап. Понимание структуры, контекста и взаимосвязей документов определяет качество проверки.',
        'Как перейти от отдельных распознанных файлов к единой системе взаимосвязанных данных и подтверждений.',
        'Подходы к сопоставлению показателей, определению несоответствий и формированию доказательной базы.'
      ];
      titles.forEach(function (title, i) {
        if (i >= articleTitles.length) { var card = title.closest('.w-dyn-item,.blog-item,.blog-card'); if (card) card.hidden = true; return; }
        title.textContent = articleTitles[i];
        var card = title.closest('.w-dyn-item,.blog-item,.blog-card') || title.parentElement;
        if (card && !card.querySelector('.site-copy-excerpt')) {
          var excerpt = document.createElement('p');
          excerpt.className = 'site-copy-excerpt _14px-text white-text';
          excerpt.textContent = excerpts[i];
          card.appendChild(excerpt);
        }
      });
      set('.blogs-descr', 'Исследуем возможности искусственного интеллекта в анализе документации, автоматизации финансового контроля и проверке достоверности данных. Phystech Trace делится практическими наблюдениями, технологическими решениями и исследованиями в области Document Intelligence.', 0, section);
      hide('.blog-data,.blog-point', section);
      setMany('.all-blogs-section ._16px-text', ['Рекомендуемые материалы', 'Мысли и исследования'], section);
    }
  }

  function casesPage() {
    var hero = document.querySelector('.hero.cs');
    if (hero) {
      var title = hero.querySelector('h1');
      if (title) title.textContent = 'Примеры работы | Интеллектуальная проверка документации';
    }
    var section = document.querySelector('.all-blogs-section.cs');
    if (section) {
      set('._16px-text', 'Демонстрационный кейс', 0, section);
      setMany('.cs-title', ['Проверка достоверности отчётности по первичным учётным документам', 'Основные результаты'], section);
      set('.highlight-text-alt', 'Как превратить комплект разрозненных документов в связанную систему данных, подтверждений и результатов проверки.', 0, section);
      setMany('.testim-num.cs', ['01', '02'], section);
      setMany('.blog-point.cs', [
        'Задача: проверить показатели отчёта по первичным учётным документам; ручной поиск подтверждений усложняется с ростом числа файлов.',
        'Решение: определить типы документов, извлечь показатели, связать файлы и выполнить интеллектуальную сверку.',
        'Результат: структурированный отчёт с расхождениями, ссылками на источники и рекомендацией — подписать документ или вернуть на доработку.'
      ], section);
      if (!section.querySelector('.site-copy-case-result')) {
        var result = document.createElement('div');
        result.className = 'site-copy-case-result';
        result.innerHTML = '<h3 class="_30px-text white">Задача</h3><p class="_16px-text white-text">Необходимо проверить показатели отчёта внутреннего заказчика на основании первичных учётных документов. Ручной анализ требует времени, а поиск подтверждений и сопоставление значений усложняются при увеличении количества файлов.</p><h3 class="_30px-text white">Решение</h3><p class="_16px-text white-text">Phystech Trace последовательно анализирует документацию, определяет типы документов, извлекает необходимые показатели, устанавливает связи между файлами и выполняет интеллектуальную сверку данных.</p><h3 class="_30px-text white">Результат</h3><p class="_16px-text white-text">Формируется структурированный результат проверки с выявленными расхождениями, ссылками на подтверждающие материалы и итоговой рекомендацией — подписать отчёт или вернуть его на доработку.</p><h3 class="_30px-text white">Основные результаты</h3><p class="_16px-text white-text">Единая картина документации: все обработанные материалы рассматриваются в контексте общей задачи.</p><p class="_16px-text white-text">Прослеживаемость показателей: возможность перейти от результата проверки к исходному документу и подтверждающим сведениям.</p><p class="_16px-text white-text">Выявление несоответствий и недостатка подтверждающих материалов.</p><p class="_16px-text white-text">Обоснованное заключение: структурированный итог проверки с рекомендацией по дальнейшим действиям.</p>';
        result.querySelectorAll('h3').forEach(function (heading) {
          var replacement = document.createElement('h2');
          replacement.className = heading.className;
          replacement.textContent = heading.textContent;
          heading.replaceWith(replacement);
        });
        section.appendChild(result);
      }
      var cards = $('.cs-title', section);
      if (cards[1]) {
        var parent = cards[1].closest('.w-dyn-item,.cs-card,.blog-item');
        if (parent) parent.hidden = true;
      }
    }
  }

  function demoPage() {
    var hero = document.querySelector('.hero.demo');
    if (hero) {
      set('h1.hero-home.demo', '30 минут. Реальная демонстрация.', 0, hero);
      set('h1.hero-home.demo', 'Без сценария продаж.', 1, hero);
      set('.text-block-5', 'Посмотрите, как Phystech Trace анализирует документы, устанавливает связи между источниками и проверяет достоверность отчётности. Покажем основные возможности платформы, разберём последовательность обработки документов и ответим на вопросы о применении решения в ваших процессах.', 0, hero);
    }
    var labels = $('form label');
    var fieldNames = ['Имя', 'Фамилия', 'Рабочая электронная почта', 'Название клиники', 'Какая система EMR/PMS используется?'];
    labels.slice(0, fieldNames.length).forEach(function (label, i) { label.textContent = fieldNames[i]; });
    var form = document.querySelector('form');
    if (form) {
      [['first_name', 'given-name'], ['last_name', 'family-name'], ['email', 'email'], ['practice_name', 'organization']].forEach(function (entry) {
        var field = form.querySelector('[name="' + entry[0] + '"]');
        if (field) field.autocomplete = entry[1];
      });
      var submit = form.querySelector('input[type="submit"]');
      if (submit) submit.value = 'Зарегистрироваться';
      var honeypot = form.querySelector('[name="website_url"]');
      if (honeypot) {
        honeypot.tabIndex = -1;
        honeypot.setAttribute('aria-hidden', 'true');
      }
    }
    if (form && !form.querySelector('.site-document-question')) {
      var source = form.querySelector('textarea,input[type="text"]');
      var wrapper = document.createElement('div');
      wrapper.className = source && source.parentElement ? source.parentElement.className : 'site-document-question';
      wrapper.classList.add('site-document-question');
      var label = document.createElement('label');
      label.className = labels[0] ? labels[0].className : '';
      label.textContent = 'Какие документы необходимо проверять?';
      var field = document.createElement('textarea');
      field.className = source ? source.className : 'input-white w-input';
      field.id = 'documents-to-review';
      field.name = 'documents_to_review';
      field.autocomplete = 'off';
      field.placeholder = 'Какие документы необходимо проверять?';
      field.rows = 3;
      label.htmlFor = field.id;
      wrapper.append(label, field);
      form.appendChild(wrapper);
    }
    setMany('.footer-transp.bottom-links', ['HIPAA', 'Условия использования', 'Политика конфиденциальности']);
  }

  function apply() {
    if (document.documentElement.dataset.phystechCopyApplied === 'true') {
      document.documentElement.removeAttribute('data-phystech-copy-pending');
      return;
    }
    document.documentElement.dataset.phystechCopyApplied = 'true';
    try {
      shared();
      if (page === '/') {
        document.title = 'Phystech Trace — проверка отчётности';
        home();
      } else if (page === '/compare') {
        document.title = 'Сравнение решений | Phystech Trace';
        comparePage();
      } else if (page === '/blog') {
        document.title = 'Phystech Trace Blog: технологии интеллектуальной обработки документов';
        blogPage();
      } else if (page === '/case-studies') {
        document.title = 'Примеры работы | Phystech Trace';
        casesPage();
      } else if (page === '/book-a-demo') {
        window.location.replace('/register');
        return;
      }
    } finally {
      document.documentElement.removeAttribute('data-phystech-copy-pending');
    }
  }

  if (document.documentElement.dataset.phystechLocalized === 'true') apply();
  else document.addEventListener('phystech-localized', apply, { once: true });
}());
