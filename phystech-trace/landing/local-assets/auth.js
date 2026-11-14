(function () {
  'use strict';
  var form = document.querySelector('#auth-form');
  var registering = document.body.dataset.auth === 'register';
  var error = document.querySelector('#form-error');
  var submit = form.querySelector('[type=submit]');
  var password = document.querySelector('#password');
  var email = document.querySelector('#email');
  var next = '/app/';
  try {
    var requested = new URL(new URLSearchParams(location.search).get('next') || '/app/', location.origin);
    if (requested.origin === location.origin && requested.pathname.startsWith('/app/')) next = requested.pathname + requested.search + requested.hash;
  } catch (_) {}
  document.querySelectorAll('[data-auth-link]').forEach(function (link) {
    if (next !== '/app/') link.href += '?next=' + encodeURIComponent(next);
  });
  document.querySelector('#reveal-password').addEventListener('click', function () {
    var visible = password.type === 'password';
    password.type = visible ? 'text' : 'password';
    this.textContent = visible ? 'Скрыть' : 'Показать';
    this.setAttribute('aria-pressed', String(visible));
  });
  [email, password].forEach(function (field) {
    field.addEventListener('input', function () {
      field.removeAttribute('aria-invalid');
      error.textContent = '';
    });
  });
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (submit.disabled) return;
    error.textContent = '';
    var missing = !email.value.trim() ? email : !password.value ? password : null;
    if (missing) {
      missing.setAttribute('aria-invalid', 'true');
      error.textContent = missing === email ? 'Укажите почту' : 'Введите пароль';
      missing.focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = registering ? 'Создаём аккаунт…' : 'Входим…';
    try {
      var response = await fetch('/api/auth/' + (registering ? 'register' : 'login'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.value.trim(), password: password.value })
      });
      var payload = await response.json().catch(function () { return {}; });
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Не удалось продолжить. Проверьте поля и попробуйте ещё раз.');
      location.assign(next);
    } catch (failure) {
      error.textContent = failure instanceof TypeError ? 'Нет связи с сервером. Попробуйте ещё раз.' : failure.message;
      submit.disabled = false;
      submit.textContent = registering ? 'Зарегистрироваться' : 'Войти';
    }
  });
}());
