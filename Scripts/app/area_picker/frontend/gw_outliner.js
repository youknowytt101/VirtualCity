// Domain: game-workbench / scene-outliner
// Owns: scene outline rendering and active-row synchronization.
// AI handoff: For missing rows, labels, or outline selection state, start here.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});

  function sceneOutlineTypeLabel(obj) {
    var type = obj && obj.userData ? obj.userData.assetType : '';
    var labels = {
      terrain: '地形',
      buildings: '建筑',
      roads: '道路',
      character: '角色',
      model: '模型'
    };
    return labels[type] || type || '模型';
  }

  function createSceneOutliner(options) {
    var body = options.body;
    var onSelect = options.onSelect;

    function refreshActive(selectedObject) {
      if (!body) return;
      var rows = body.querySelectorAll('.scene-outline-row');
      for (var i = 0; i < rows.length; i++) rows[i].classList.remove('is-active');
      if (selectedObject && selectedObject.userData.outlineRow) {
        selectedObject.userData.outlineRow.classList.add('is-active');
      }
    }

    function rebuild(items, selectedObject) {
      if (!body) return;
      body.innerHTML = '';
      if (!items.length) {
        var empty = document.createElement('div');
        empty.className = 'scene-outline-empty';
        empty.textContent = '场景为空';
        body.appendChild(empty);
        return;
      }

      var table = document.createElement('div');
      table.className = 'scene-outline-table';
      var head = document.createElement('div');
      head.className = 'scene-outline-head';
      var headerLabel = document.createElement('div');
      headerLabel.className = 'scene-outline-cell scene-outline-label';
      headerLabel.textContent = '项目标签';
      var headerType = document.createElement('div');
      headerType.className = 'scene-outline-cell scene-outline-type';
      headerType.textContent = '类型';
      head.appendChild(headerLabel);
      head.appendChild(headerType);
      table.appendChild(head);

      items.forEach(function(obj) {
        var row = document.createElement('button');
        row.type = 'button';
        row.className = 'scene-outline-row';
        row.dataset.assetType = obj.userData.assetType || '';
        var label = obj.userData.assetLabel || obj.name || '对象';
        var type = sceneOutlineTypeLabel(obj);
        var labelCell = document.createElement('span');
        labelCell.className = 'scene-outline-cell scene-outline-label';
        var swatch = document.createElement('span');
        swatch.className = 'scene-outline-swatch';
        var labelText = document.createElement('span');
        labelText.className = 'scene-outline-name';
        labelText.textContent = label;
        var typeCell = document.createElement('span');
        typeCell.className = 'scene-outline-cell scene-outline-type';
        typeCell.textContent = sceneOutlineTypeLabel(obj);
        labelCell.appendChild(swatch);
        labelCell.appendChild(labelText);
        row.appendChild(labelCell);
        row.appendChild(typeCell);
        row.setAttribute('aria-label', label + '，类型 ' + type);
        row.addEventListener('click', function() { onSelect(obj); });
        obj.userData.outlineRow = row;
        table.appendChild(row);
      });

      body.appendChild(table);
      refreshActive(selectedObject);
    }

    return {
      rebuild: rebuild,
      refreshActive: refreshActive
    };
  }

  GW.createSceneOutliner = createSceneOutliner;
})();
