// Domain: asset-library
// Owns: Local asset directory persistence and asset tree status in the game workspace.
// AI handoff: For asset directory save or tree refresh issues, check /asset-dir in API_CONTRACT.md.
(function() {
  'use strict';

  var input = document.getElementById('asset-dir-input');
  var form = document.getElementById('asset-dir-form');
  var status = document.getElementById('asset-dir-status');
  var tree = document.getElementById('asset-dir-tree');
  if (!input || !form) return;

  function showStatus(text) {
    if (status) status.textContent = text || '';
  }

  function renderTree(subdirs, ready) {
    if (!tree) return;
    tree.innerHTML = '';
    (subdirs || []).forEach(function(item) {
      var li = document.createElement('li');
      li.className = 'asset-dir-cat' + (ready && item.exists ? ' is-ready' : '');
      var name = document.createElement('span');
      name.className = 'asset-dir-cat-name';
      name.textContent = item.name;
      var desc = document.createElement('span');
      desc.className = 'asset-dir-cat-desc';
      desc.textContent = item.description;
      li.appendChild(name);
      li.appendChild(desc);
      tree.appendChild(li);
    });
  }

  function applyStatus(d) {
    if (!d) return;
    if (document.activeElement !== input) input.value = d.asset_dir || '';
    renderTree(d.subdirs, d.asset_dir_exists);
    if (d.asset_dir && d.asset_dir_exists === false) showStatus('目录不存在');
  }

  fetch('/asset-dir')
    .then(function(r) { return r.json(); })
    .then(applyStatus)
    .catch(function() {});

  form.addEventListener('submit', function(event) {
    event.preventDefault();
    showStatus('保存中…');
    fetch('/asset-dir', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: input.value.trim() })
    })
      .then(function(r) { return r.json(); })
      .then(function(d) {
        showStatus(d && d.message ? d.message : '已保存');
        if (d && d.asset_dir) applyStatus(d.asset_dir);
      })
      .catch(function() { showStatus('保存失败'); });
  });
})();
