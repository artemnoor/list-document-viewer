(function () {
  'use strict';

  var dictionary = Object.create(null);
  var pending = false;
  var excluded = /^(SCRIPT|STYLE|NOSCRIPT|TEXTAREA)$/;

  function replaceBrand(value) {
    if (/\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b/.test(value) || /(?:https?:\/\/|\bwww\.)/i.test(value)) return value;
    return value.replace(/Transform\s*9/gi, 'Phystech Trace');
  }

  function translateValue(value) {
    var trimmed = value.trim();
    if (!trimmed) return value;
    var normalized = trimmed.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ');
    var translated = dictionary[trimmed];
    if (translated == null || translated === '') translated = dictionary[normalized];
    if (translated == null || translated === '') translated = replaceBrand(trimmed);
    translated = replaceBrand(translated);
    if (translated === trimmed) return value;
    var start = value.match(/^\s*/)[0];
    var end = value.match(/\s*$/)[0];
    return start + translated + end;
  }

  function applyTo(root) {
    if (!root || !dictionary) return;
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        var parent = node.parentElement;
        if (!parent || excluded.test(parent.tagName) || parent.closest('script,style,noscript,textarea')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var node;
    while ((node = walker.nextNode())) node.nodeValue = translateValue(node.nodeValue);

    var elements = root.nodeType === 1 ? [root].concat(Array.from(root.querySelectorAll('*'))) : Array.from(root.querySelectorAll ? root.querySelectorAll('*') : []);
    elements.forEach(function (el) {
      ['placeholder', 'aria-label', 'title', 'alt', 'value'].forEach(function (name) {
        if (el.hasAttribute && el.hasAttribute(name)) el.setAttribute(name, translateValue(el.getAttribute(name)));
      });
    });
    if (root === document || root === document.documentElement) {
      document.documentElement.lang = 'ru';
      document.title = translateValue(document.title);
      document.querySelectorAll('meta[name="description"],meta[property="og:description"],meta[name="twitter:description"]').forEach(function (meta) {
        meta.content = translateValue(meta.content);
      });
      document.querySelectorAll('meta[property="og:title"],meta[name="twitter:title"]').forEach(function (meta) {
        meta.content = translateValue(meta.content);
      });
      installLogo();
      removePhoneCallWidgets();
    }
  }

  function installLogo() {
    document.querySelectorAll('.logo-wrap').forEach(function (link) {
      var white = link.querySelector('img.logo-white');
      var black = link.querySelector('img.logo-black');
      if (white && white.getAttribute('src') !== '/local-assets/phystech-trace-logo-clean.png') white.src = '/local-assets/phystech-trace-logo-clean.png';
      if (black && black.getAttribute('src') !== '/local-assets/phystech-trace-logo-clean.png') black.src = '/local-assets/phystech-trace-logo-clean.png';
      if (white) { white.alt = 'Phystech Trace'; white.classList.add('phystech-trace-logo'); }
      if (black) { black.alt = ''; black.classList.add('phystech-trace-logo'); }
      link.dataset.phystechLogo = 'true';
      link.setAttribute('aria-label', 'Phystech Trace — на главную');
    });
    document.querySelectorAll('.footer-logo').forEach(function (logo) {
      logo.src = '/local-assets/phystech-trace-logo-clean.png';
      logo.alt = 'Phystech Trace';
    });
    document.querySelectorAll('img[alt]').forEach(function (logo) {
      if (/transform\s*9.*logo/i.test(logo.alt)) logo.alt = 'Phystech Trace';
    });
  }

  function removePhoneCallWidgets() {
    document.querySelectorAll('.home-hero-form').forEach(function (form) {
      var block = form.closest('.hero-bottom-block');
      if (block) block.remove();
      else form.remove();
    });
    document.querySelectorAll('input[placeholder="Your phone number"]').forEach(function (input) {
      var block = input.closest('.hero-bottom-block');
      if (block) block.remove();
      else input.remove();
    });
    document.querySelectorAll('.get-a-call').forEach(function (link) { link.remove(); });
  }

  function observe() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () {
      pending = false;
      applyTo(document.body);
      installLogo();
      removePhoneCallWidgets();
    });
  }

  fetch('/local-assets/translations.ru.json', { cache: 'no-store' })
    .then(function (response) { if (!response.ok) throw new Error('Translation dictionary unavailable'); return response.json(); })
    .then(function (data) {
      dictionary = data || Object.create(null);
      document.documentElement.dataset.phystechLocalized = 'true';
      applyTo(document.documentElement);
      new MutationObserver(observe).observe(document.body, { childList: true, characterData: true, subtree: true });
      document.dispatchEvent(new CustomEvent('phystech-localized'));
    })
    .catch(function () {
      dictionary = Object.create(null);
      document.documentElement.dataset.phystechLocalized = 'fallback';
      applyTo(document.documentElement);
      installLogo();
      removePhoneCallWidgets();
      document.dispatchEvent(new CustomEvent('phystech-localized'));
    });
}());
