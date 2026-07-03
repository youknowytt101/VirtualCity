// Domain: cloud-assets
// Owns: Right-side game editor cloud asset browser.
// AI handoff: First version is read-only and backed by /cloud-assets local manifest data.
(function() {
  'use strict';

  var browser = document.getElementById('cloud-asset-browser');
  if (!browser) return;

  var statusEl = document.getElementById('cloud-asset-status');
  var refreshBtn = document.getElementById('cloud-asset-refresh');
  var categoryHost = document.getElementById('cloud-asset-categories');
  var grid = document.getElementById('cloud-asset-grid');
  var state = {
    filter: 'all',
    payload: null,
    selectedId: ''
  };

  var categories = [
    { id: 'all', label: '全部' },
    { id: 'material', label: '材质' }
  ];

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || '';
  }

  function setLoading(loading) {
    if (!refreshBtn) return;
    refreshBtn.classList.toggle('is-loading', !!loading);
    refreshBtn.disabled = !!loading;
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
    if (category === 'all') return totalCount(counts, assets);
    return Number(counts && counts[category]) || 0;
  }

  function categoryLabel(category) {
    for (var i = 0; i < categories.length; i += 1) {
      if (categories[i].id === category) return categories[i].label;
    }
    return '其他';
  }

  function makeEmpty(text) {
    var empty = document.createElement('div');
    empty.className = 'cloud-asset-empty';
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
      button.className = 'cloud-asset-category';
      button.dataset.category = item.id;
      button.classList.toggle('is-active', state.filter === item.id);
      button.setAttribute('aria-pressed', state.filter === item.id ? 'true' : 'false');
      label.textContent = item.label;
      count.className = 'cloud-asset-category-count';
      count.textContent = String(categoryCount(item.id, counts, assets));
      button.appendChild(label);
      button.appendChild(count);
      button.addEventListener('click', function() {
        state.filter = item.id;
        renderCloudAssets(state.payload);
      });
      categoryHost.appendChild(button);
    });
  }

  function visibleAssets(payload) {
    var assets = payload && Array.isArray(payload.assets) ? payload.assets : [];
    if (state.filter === 'all') return assets;
    return assets.filter(function(asset) {
      return asset.category === state.filter;
    });
  }

  function renderCloudAssetCard(asset) {
    var card = document.createElement('button');
    var swatch = document.createElement('span');
    var main = document.createElement('span');
    var name = document.createElement('span');
    var meta = document.createElement('span');
    var desc = document.createElement('span');
    var footer = document.createElement('span');
    var runtime = asset.runtimeType || 'Material';
    var source = asset.source || 'server';
    var assetId = asset.id || asset.name || '';

    card.type = 'button';
    card.className = 'cloud-asset-card';
    card.dataset.cloudAssetId = assetId;
    card.dataset.cloudAssetCategory = asset.category || 'other';
    card.dataset.runtimeType = runtime;
    card.setAttribute('role', 'listitem');
    card.setAttribute('aria-pressed', state.selectedId === assetId ? 'true' : 'false');
    card.classList.toggle('is-selected', state.selectedId === assetId);
    card.title = asset.description || asset.name || '';

    swatch.className = 'cloud-asset-swatch';
    swatch.style.background = asset.swatch || '#8f9aa3';

    main.className = 'cloud-asset-main';
    name.className = 'cloud-asset-name';
    meta.className = 'cloud-asset-meta';
    desc.className = 'cloud-asset-description';
    footer.className = 'cloud-asset-footer';

    name.textContent = asset.name || '未命名资产';
    meta.textContent = categoryLabel(asset.category || 'other') + ' · ' + runtime;
    desc.textContent = asset.description || '服务器资产';
    footer.textContent = source + (asset.materialKind ? ' · ' + asset.materialKind : '');

    main.appendChild(name);
    main.appendChild(meta);
    main.appendChild(desc);
    main.appendChild(footer);
    card.appendChild(swatch);
    card.appendChild(main);
    card.addEventListener('click', function() {
      state.selectedId = assetId;
      renderCloudAssets(state.payload);
    });
    return card;
  }

  function renderCloudAssets(payload) {
    state.payload = payload || {};
    renderCategories(state.payload);
    if (!grid) return;
    grid.innerHTML = '';
    if (!state.payload.available) {
      grid.appendChild(makeEmpty(state.payload.message || '云端资产库不可用'));
      return;
    }
    var assets = visibleAssets(state.payload);
    if (!assets.length) {
      grid.appendChild(makeEmpty(state.filter === 'all' ? '云端资产库暂无资产' : '当前分类暂无云端资产'));
      return;
    }
    assets.forEach(function(asset) {
      grid.appendChild(renderCloudAssetCard(asset));
    });
  }

  function statusText(payload) {
    if (!payload || !payload.ok) return payload && payload.message ? payload.message : '云端资产读取失败';
    if (!payload.available) return payload.message || '云端资产库不可用';
    var count = Array.isArray(payload.assets) ? payload.assets.length : 0;
    return '当前服务器 · ' + count + '/' + totalCount(payload.counts, payload.assets) + ' 个资产';
  }

  function loadCloudAssets() {
    setLoading(true);
    setStatus('读取云端资产...');
    fetch('/cloud-assets')
      .then(function(r) { return r.json(); })
      .then(function(payload) {
        setStatus(statusText(payload));
        renderCloudAssets(payload);
      })
      .catch(function() {
        var payload = { ok: false, available: false, message: '云端资产读取失败', assets: [], counts: {} };
        setStatus(payload.message);
        renderCloudAssets(payload);
      })
      .finally(function() {
        setLoading(false);
      });
  }

  if (refreshBtn) refreshBtn.addEventListener('click', loadCloudAssets);
  window.VC_CLOUD_ASSETS = {
    refresh: loadCloudAssets,
    renderCloudAssets: renderCloudAssets
  };
  loadCloudAssets();
})();
