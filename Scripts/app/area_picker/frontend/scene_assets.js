// Domain: scene-assets
// Owns: Editor bottom project asset browser.
// AI handoff: For bottom asset browser issues, check /scene-assets and scene-root-changed refreshes.
(function() {
  'use strict';

  var browser = document.getElementById('scene-asset-browser');
  if (!browser) return;

  var statusEl = document.getElementById('scene-asset-status');
  var refreshBtn = document.getElementById('scene-asset-refresh');
  var categoryHost = document.getElementById('scene-asset-categories');
  var grid = document.getElementById('scene-asset-grid');
  var state = {
    filter: 'all',
    payload: null
  };

  var categories = [
    { id: 'all', label: '全部' },
    { id: 'model', label: '模型' },
    { id: 'other', label: '其他' }
  ];

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || '';
  }

  function setLoading(loading) {
    if (!refreshBtn) return;
    refreshBtn.classList.toggle('is-loading', !!loading);
    refreshBtn.disabled = !!loading;
  }

  function categoryLabel(category) {
    for (var i = 0; i < categories.length; i += 1) {
      if (categories[i].id === category) return categories[i].label;
    }
    return '其他';
  }

  function totalCount(counts, assets) {
    if (!counts) return assets ? assets.length : 0;
    var total = 0;
    Object.keys(counts).forEach(function(key) {
      total += Number(counts[key]) || 0;
    });
    return total;
  }

  function categoryCount(category, counts, assets) {
    var total = totalCount(counts, assets);
    var modelCount = Number(counts && counts.model) || 0;
    if (category === 'all') return total;
    if (category === 'model') return modelCount;
    return Math.max(0, total - modelCount);
  }

  function makeEmpty(text) {
    var empty = document.createElement('div');
    empty.className = 'scene-asset-empty';
    empty.textContent = text;
    return empty;
  }

  function renderCategories(payload) {
    if (!categoryHost) return;
    var counts = payload && payload.counts ? payload.counts : {};
    var assets = payload && Array.isArray(payload.assets) ? payload.assets : [];
    categoryHost.innerHTML = '';
    categories.forEach(function(item) {
      var button = document.createElement('button');
      var label = document.createElement('span');
      var count = document.createElement('span');
      button.type = 'button';
      button.className = 'scene-asset-category';
      button.dataset.category = item.id;
      button.classList.toggle('is-active', state.filter === item.id);
      button.setAttribute('aria-pressed', state.filter === item.id ? 'true' : 'false');
      label.textContent = item.label;
      count.className = 'scene-asset-category-count';
      count.textContent = String(categoryCount(item.id, counts, assets));
      button.appendChild(label);
      button.appendChild(count);
      button.addEventListener('click', function() {
        state.filter = item.id;
        renderAssets(state.payload);
      });
      categoryHost.appendChild(button);
    });
  }

  function renderAssetItem(asset) {
    var item = document.createElement('button');
    var thumbnail = document.createElement('span');
    var main = document.createElement('span');
    var name = document.createElement('span');
    var path = document.createElement('span');
    var meta = document.createElement('span');
    var category = asset.category || 'other';
    var extension = asset.extension || category;
    var assetName = asset.display_name || asset.name || '未命名资产';
    var assetUrl = asset.url || (asset.relative_path ? '/scene-asset-file?path=' + encodeURIComponent(asset.relative_path) : '');

    item.type = 'button';
    item.className = 'scene-asset-item';
    item.dataset.category = category;
    if (asset.source) item.dataset.source = asset.source;
    item.dataset.sceneAssetPath = asset.relative_path || '';
    item.dataset.sceneAssetCategory = category;
    item.dataset.sceneAssetName = assetName;
    item.dataset.sceneAssetUrl = assetUrl;
    item.setAttribute('role', 'listitem');
    item.title = asset.relative_path || asset.name || '';

    thumbnail.className = 'scene-asset-thumbnail scene-asset-icon';
    thumbnail.textContent = extension.slice(0, 4) || category.slice(0, 4);

    main.className = 'scene-asset-main';
    name.className = 'scene-asset-name';
    path.className = 'scene-asset-path';
    meta.className = 'scene-asset-meta';
    name.textContent = assetName;
    path.textContent = asset.folder || '根目录';
    meta.textContent = categoryLabel(category) + ' · ' + (asset.size_label || '--');

    main.appendChild(name);
    main.appendChild(path);
    item.appendChild(thumbnail);
    item.appendChild(main);
    item.appendChild(meta);
    return item;
  }

  function visibleAssets(payload) {
    var assets = payload && Array.isArray(payload.assets) ? payload.assets : [];
    if (state.filter === 'all') return assets;
    if (state.filter === 'other') {
      return assets.filter(function(asset) {
        return asset.category !== 'model';
      });
    }
    return assets.filter(function(asset) {
      return asset.category === state.filter;
    });
  }

  function renderAssets(payload) {
    state.payload = payload || {};
    renderCategories(state.payload);
    if (!grid) return;
    grid.innerHTML = '';
    if (!state.payload.available) {
      grid.appendChild(makeEmpty(state.payload.message || '未设置工程目录'));
      return;
    }
    var assets = visibleAssets(state.payload);
    if (!assets.length) {
      grid.appendChild(makeEmpty(state.filter === 'all' ? '当前工程目录暂无资产' : '当前分类暂无资产'));
      return;
    }
    assets.forEach(function(asset) {
      grid.appendChild(renderAssetItem(asset));
    });
  }

  function statusText(payload) {
    if (!payload || !payload.ok) return payload && payload.message ? payload.message : '工程资产读取失败';
    if (!payload.available) return payload.message || '未设置工程目录';
    var count = Array.isArray(payload.assets) ? payload.assets.length : 0;
    var total = totalCount(payload.counts, payload.assets);
    var suffix = payload.truncated ? ' · 已截断' : '';
    return (payload.scene_root || '工程目录') + ' · ' + count + '/' + total + ' 个资产' + suffix;
  }

  function loadSceneAssets() {
    setLoading(true);
    setStatus('读取工程目录...');
    fetch('/scene-assets')
      .then(function(r) { return r.json(); })
      .then(function(payload) {
        setStatus(statusText(payload));
        renderAssets(payload);
      })
      .catch(function() {
        var payload = { ok: false, available: false, message: '工程资产读取失败', assets: [], counts: {} };
        setStatus(payload.message);
        renderAssets(payload);
      })
      .finally(function() {
        setLoading(false);
      });
  }

  if (refreshBtn) refreshBtn.addEventListener('click', loadSceneAssets);
  window.addEventListener('scene-root-changed', loadSceneAssets);
  window.VC_SCENE_ASSETS = { refresh: loadSceneAssets, renderAssets: renderAssets };
  loadSceneAssets();
})();
