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
    var outlineLabelWidth = null;
    var columnResizeState = null;

    function clamp(n, min, max) {
      return Math.max(min, Math.min(max, n));
    }

    function setSplitterA11y(table, splitter, width) {
      var rect = table.getBoundingClientRect();
      var max = Math.max(88, Math.floor(rect.width - 78));
      splitter.setAttribute('aria-valuemin', '88');
      splitter.setAttribute('aria-valuemax', String(max));
      splitter.setAttribute('aria-valuenow', String(Math.round(width)));
    }

    function setOutlineLabelWidth(table, nextWidth) {
      var rect = table.getBoundingClientRect();
      var maxWidth = Math.max(88, rect.width - 78);
      var width = clamp(nextWidth, 88, maxWidth);
      outlineLabelWidth = Math.round(width);
      table.style.setProperty('--scene-outline-label-width', outlineLabelWidth + 'px');
      var splitter = table.querySelector('.scene-outline-column-splitter');
      if (splitter) setSplitterA11y(table, splitter, outlineLabelWidth);
    }

    function currentOutlineLabelWidth(table) {
      if (outlineLabelWidth) return outlineLabelWidth;
      var rect = table.getBoundingClientRect();
      return Math.max(88, rect.width - 88);
    }

    function labelWidthFromPointer(table, event) {
      var rect = table.getBoundingClientRect();
      return event.clientX - rect.left - 8;
    }

    function finishColumnResize() {
      if (!columnResizeState) return;
      var state = columnResizeState;
      columnResizeState = null;
      state.table.classList.remove('is-resizing-columns');
      try { state.splitter.releasePointerCapture(state.pointerId); } catch (e) {}
      window.removeEventListener('pointermove', handleColumnResizeMove);
      window.removeEventListener('pointerup', finishColumnResize);
      window.removeEventListener('pointercancel', finishColumnResize);
    }

    function handleColumnResizeMove(event) {
      if (!columnResizeState) return;
      event.preventDefault();
      setOutlineLabelWidth(columnResizeState.table, labelWidthFromPointer(columnResizeState.table, event));
    }

    function beginColumnResize(table, splitter, event) {
      if (event.button !== 0) return;
      event.preventDefault();
      columnResizeState = {
        table: table,
        splitter: splitter,
        pointerId: event.pointerId
      };
      table.classList.add('is-resizing-columns');
      try { splitter.setPointerCapture(event.pointerId); } catch (e) {}
      setOutlineLabelWidth(table, labelWidthFromPointer(table, event));
      window.addEventListener('pointermove', handleColumnResizeMove);
      window.addEventListener('pointerup', finishColumnResize);
      window.addEventListener('pointercancel', finishColumnResize);
    }

    function nudgeColumnWidth(table, splitter, delta) {
      setOutlineLabelWidth(table, currentOutlineLabelWidth(table) + delta);
      splitter.focus();
    }

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
      var splitter = document.createElement('button');
      splitter.type = 'button';
      splitter.className = 'scene-outline-column-splitter';
      splitter.setAttribute('aria-label', '调整项目标签和类型列宽');
      splitter.setAttribute('role', 'separator');
      splitter.setAttribute('aria-orientation', 'vertical');
      splitter.addEventListener('pointerdown', function(event) {
        beginColumnResize(table, splitter, event);
      });
      splitter.addEventListener('keydown', function(event) {
        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          nudgeColumnWidth(table, splitter, -12);
        } else if (event.key === 'ArrowRight') {
          event.preventDefault();
          nudgeColumnWidth(table, splitter, 12);
        }
      });
      head.appendChild(headerLabel);
      head.appendChild(splitter);
      head.appendChild(headerType);
      table.appendChild(head);
      if (outlineLabelWidth) table.style.setProperty('--scene-outline-label-width', outlineLabelWidth + 'px');

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
