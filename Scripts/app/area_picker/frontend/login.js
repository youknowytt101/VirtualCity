// Domain: login-page
// Owns: the standalone /login page -- development one-click login.
// AI handoff: server-side session/cookie logic lives in server.py + auth.py.
(function() {
  'use strict';

  function setStatus(el, message, isError) {
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('is-error', Boolean(isError));
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(function(response) {
      return response.json();
    });
  }

  function redirectToApp() {
    var params = new URLSearchParams(window.location.search);
    window.location.href = params.get('next') || '/';
  }

  function bindLoginForm() {
    var form = document.getElementById('login-form-login');
    var statusEl = document.getElementById('login-status-login');
    if (!form) return;
    form.addEventListener('submit', function(event) {
      event.preventDefault();
      var submitButton = document.getElementById('login-submit-login');
      setStatus(statusEl, '登录中...', false);
      if (submitButton) submitButton.disabled = true;
      postJson('/auth/login', { dev_login: true })
        .then(function(res) {
          if (!res || !res.ok) {
            setStatus(statusEl, (res && res.message) || '登录失败', true);
            return;
          }
          setStatus(statusEl, '登录成功，正在跳转...', false);
          redirectToApp();
        })
        .catch(function() {
          setStatus(statusEl, '网络错误，请重试', true);
        })
        .finally(function() {
          if (submitButton) submitButton.disabled = false;
        });
    });
  }

  bindLoginForm();
})();
