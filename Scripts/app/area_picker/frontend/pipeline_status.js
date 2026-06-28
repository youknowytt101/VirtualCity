// Pipeline status, logs, task submission, and export controls.

// Domain: pipeline-status
// Owns: Run/export buttons, status stream, logs, progress UI, failure summary, and data-source rendering.
// AI handoff: For Houdini run state or stuck progress, start with applySharedStatus, applyStatus, and submitSelectedArea.
function updateExportButton(available, running) {
  var btn = document.getElementById('export-btn');
  btn.disabled = !available || !!running;
}

function setRunStatus(state, title, pct, detail) {
  var panel = document.getElementById('run-status-panel');
  var titleEl = document.getElementById('run-status-title');
  var pctEl = document.getElementById('run-status-pct');
  var bar = document.getElementById('run-status-bar');
  var detailEl = document.getElementById('run-status-detail');
  if (!panel || !titleEl || !pctEl || !bar || !detailEl) return;
  var n = Math.max(0, Math.min(100, Number(pct) || 0));
  panel.className = 'run-status-panel status-' + state;
  titleEl.textContent = title;
  pctEl.textContent = n + '%';
  // Only animate forward progress; resets and failures snap back immediately.
  var prev = Number(bar.dataset.pct) || 0;
  if (n < prev) {
    var saved = bar.style.transition;
    bar.style.transition = 'none';
    bar.style.transform = 'scaleX(' + (n / 100) + ')';
    void bar.offsetWidth;
    bar.style.transition = saved;
  } else {
    bar.style.transform = 'scaleX(' + (n / 100) + ')';
  }
  bar.dataset.pct = n;
  detailEl.textContent = detail || '等待任务';
}

function setRunPhase(phaseLabel) {
  var el = document.getElementById('run-status-phase');
  if (!el) return;
  if (phaseLabel) {
    el.textContent = phaseLabel;
    el.hidden = false;
  } else {
    el.textContent = '';
    el.hidden = true;
  }
}

var STAGE_DEFS = [
  { id: 'download', label: '数据下载' },
  { id: 'refine',   label: '离线精炼' },
  { id: 'houdini',  label: 'Houdini 构建' },
  { id: 'qa',       label: 'QA 质量审查' }
];
var PHASE_STAGE = {
  'created':                { idx: 0, done: false },
  'download_area_prepared': { idx: 0, done: false },
  'active_area_written':    { idx: 0, done: false },
  'acquire_osm':            { idx: 0, done: false },
  'acquire_dem':            { idx: 0, done: false },
  'acquire_buildings':      { idx: 0, done: false },
  'raw_data_acquired':      { idx: 0, done: false },
  'data_download_completed':{ idx: 0, done: true },
  'refine_data':            { idx: 1, done: false },
  'refine_data_completed':  { idx: 1, done: true },
  'houdini_preflight':      { idx: 2, done: false },
  'houdini_recook':         { idx: 2, done: false },
  'houdini_completed':      { idx: 2, done: true },
  'pipeline_completed':     { idx: 3, done: true },
  'aborted':                { idx: 0, done: false }
};

function computeStageStatuses(d) {
  var statuses = ['todo', 'todo', 'todo', 'todo'];
  if (!d) return statuses;
  var map = PHASE_STAGE[d.phase || ''];
  var failed = (d.done && !d.ok) ||
    (!d.running && d.failure_summary && d.failure_summary.available);
  if (failed) {
    var failPhase = (d.failure_summary && d.failure_summary.phase) || d.phase || '';
    var failMap = PHASE_STAGE[failPhase] || map;
    var failIdx = failMap ? failMap.idx : 0;
    for (var i = 0; i < 4; i++) {
      if (i < failIdx) statuses[i] = 'done';
      else if (i === failIdx) statuses[i] = 'fail';
    }
    return statuses;
  }
  if (d.done && d.ok) {
    if (d.operation === 'download') statuses[0] = 'done';
    else statuses = ['done', 'done', 'done', 'done'];
    return statuses;
  }
  var active = d.running || d.export_running;
  if (active && map) {
    for (var j = 0; j < 4; j++) {
      if (j < map.idx) statuses[j] = 'done';
      else if (j === map.idx) statuses[j] = map.done ? 'done' : 'active';
    }
  }
  return statuses;
}

function ensureStageDom() {
  var list = document.getElementById('run-stage-list');
  if (!list || list.childElementCount) return list;
  for (var i = 0; i < STAGE_DEFS.length; i++) {
    var row = document.createElement('div');
    row.className = 'run-stage is-todo';
    row.setAttribute('role', 'listitem');
    row.innerHTML =
      '<span class="run-stage-icon">' +
        '<span class="dot"></span>' +
        '<span class="check"><svg viewBox="0 0 24 24" aria-hidden="true">' +
          '<path d="M5 13l4 4L19 7"></path></svg></span>' +
      '</span>' +
      '<span class="run-stage-label"></span>';
    row.querySelector('.run-stage-label').textContent = STAGE_DEFS[i].label;
    list.appendChild(row);
  }
  return list;
}

function renderStageChecklist(d) {
  var list = ensureStageDom();
  if (!list) return;
  var statuses = computeStageStatuses(d);
  var rows = list.children;
  var primed = list.dataset.primed === '1';
  if (!primed) list.classList.add('no-anim');
  for (var i = 0; i < rows.length && i < statuses.length; i++) {
    rows[i].className = 'run-stage is-' + statuses[i];
    rows[i].setAttribute('aria-checked', statuses[i] === 'done' ? 'true' : 'false');
  }
  if (!primed) {
    void list.offsetWidth;
    list.classList.remove('no-anim');
    list.dataset.primed = '1';
  }
}

function failureMetricsLine(summary) {
  if (!summary) return '';
  if (summary.metrics_line) return summary.metrics_line;
  var metrics = summary.metrics || [];
  return metrics.slice(0, 6).map(function(item) {
    return (item.label || item.key || 'metric') + '=' + (item.value_label || item.value);
  }).join(', ');
}

function setFailureSummary(summary) {
  var box = document.getElementById('failure-summary');
  if (!box) return;
  var reasonEl = document.getElementById('failure-reason');
  var reportEl = document.getElementById('failure-report');
  var metricsEl = document.getElementById('failure-metrics');
  if (!summary || !summary.available) {
    box.hidden = true;
    return;
  }
  var reason = summary.reason || summary.message || '未知失败原因';
  var report = summary.report || summary.run_report || '--';
  var metrics = failureMetricsLine(summary) || '--';
  reasonEl.textContent = reason;
  reasonEl.title = reason;
  reportEl.textContent = report;
  reportEl.title = report;
  metricsEl.textContent = metrics;
  metricsEl.title = metrics;
  box.hidden = false;
}

function failureStatusDetail(summary, fallback) {
  if (!summary || !summary.available) return fallback || '[FAIL] 管线出错';
  var stage = summary.stage || summary.phase_label || '管线失败';
  if (summary.check) return stage + ': ' + summary.check;
  if (summary.phase) return stage + ' · ' + summary.phase;
  return stage;
}

function logFailureSummary(summary, returncode) {
  if (!summary || !summary.available) {
    log('[FAIL] 管线出错 (exit=' + returncode + ')', 'err');
    return;
  }
  var key = summary.key || (summary.run_id + '|' + summary.reason + '|' + summary.report);
  if (_lastFailureKey === key) return;
  _lastFailureKey = key;
  var head = '[FAIL] ' + (summary.stage || summary.phase_label || '管线出错');
  if (summary.check) head += ': ' + summary.check;
  log(head, 'err');
  if (summary.reason) log('原因: ' + summary.reason, 'err');
  var metrics = failureMetricsLine(summary);
  if (metrics) log('指标: ' + metrics, 'err');
  if (summary.warnings && summary.warnings.length) {
    var names = summary.warnings.map(function(item) { return item.name; }).filter(Boolean).join(', ');
    if (names) log('警告: ' + names, 'dim');
  }
  if (summary.report) log('QA 报告: ' + summary.report, 'dim');
  if (summary.run_report) log('运行报告: ' + summary.run_report, 'dim');
}

function updateRunStatusFromHealth(d) {
  // 阶段勾选：
  // - 任务正在运行/导出 -> 显示真实阶段
  // - 等待窗口内（已提交未翻转 running）-> 待命，避免闪到全绿
  var active = d && (d.running || d.export_running);
  renderStageChecklist((active && !_awaitingRun) ? d : null);
  if (!d) {
    setRunStatus('warn', '待命', 0, '等待选择区域');
    setRunPhase('');
    setFailureSummary(null);
    return;
  }
  if (d.running) {
    _awaitingRun = false;
    var isDownloadRun = d.operation === 'download';
    setRunStatus('warn', isDownloadRun ? '数据下载中' : '运行中', d.pct || 0, d.step_label || (isDownloadRun ? '正在下载 OSM / DEM / 建筑...' : '任务执行中'));
    setRunPhase(d.phase_label || '');
    setFailureSummary(null);
  } else if (d.export_running) {
    setRunStatus('warn', '导出中', 0, 'Houdini 正在导出 FBX');
    setRunPhase('导出 FBX');
    setFailureSummary(null);
  } else if (_awaitingRun) {
    // 已提交、等待后端翻转为 running。忽略此时 health 里残留的完成/失败态。
    setRunStatus('warn', '启动中', 0, '任务已提交，正在启动...');
    setRunPhase('');
    setFailureSummary(null);
  } else if (d.done) {
    if (d.ok) {
      setRunStatus('ok', '完成', 100, d.step_label || d.name || '任务结束');
      setRunPhase('');
      setFailureSummary(null);
    } else {
      setRunStatus('off', '失败', d.pct || 0, failureStatusDetail(d.failure_summary, d.step_label || d.name || '任务失败'));
      setRunPhase(d.phase_label || '');
      setFailureSummary(d.failure_summary);
    }
  } else if (d.failure_summary && d.failure_summary.available) {
    setRunStatus('off', '上次失败', d.pct || 0, failureStatusDetail(d.failure_summary, '上次管线失败'));
    setRunPhase('');
    setFailureSummary(d.failure_summary);
  } else {
    setRunStatus('warn', '待命', 0, selection ? '已选择区域，等待执行' : '等待选择区域');
    setRunPhase('');
    setFailureSummary(null);
  }
}

function updateSelectionButtons(running) {
  var disabled = !selection || !!running;
  document.getElementById('run-btn').disabled = disabled;
  document.getElementById('download-btn').disabled = disabled;
}

function renderDataSources(payload) {
  var status = document.getElementById('source-status');
  var list = document.getElementById('source-list');
  if (!status || !list) return;
  status.textContent = '选取区域预先下载地图数据加快Houdini自动管线构建速度';
  if (!payload || !payload.available) {
    return;
  }
  list.innerHTML = '';
  (payload.items || []).forEach(function(item) {
    var card = document.createElement('div');
    card.className = 'source-card';

    var head = document.createElement('div');
    head.className = 'source-head';
    var title = document.createElement('span');
    title.className = 'source-title';
    title.textContent = item.title || item.key || '数据';
    head.appendChild(title);

    var provider = document.createElement('div');
    provider.className = 'source-provider';
    provider.textContent = '数据源：' + (item.provider || '--');

    var detail = document.createElement('div');
    detail.className = 'source-detail';
    detail.textContent = '策略：' + (item.strategy_label || item.strategy || item.method || '--');
    detail.title = item.current || item.strategy || '';

    card.appendChild(head);
    card.appendChild(provider);
    card.appendChild(detail);
    list.appendChild(card);
  });
}

function refreshDataSources() {
  fetch('/data-sources')
  .then(function(r) { return r.json(); })
  .then(renderDataSources)
  .catch(function(e) {
    renderDataSources({ available: false, message: '数据源读取失败: ' + e });
  });
}

function refreshServiceState() {
  fetch('/health')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    applySharedStatus(d);
    refreshDataSources();
  })
  .catch(function() {
    setHoudiniBadge(false, null);
    setRunStatus('off', '离线', 0, '状态服务不可用');
  });
}

var LOG_MAX_LINES = 800;
var _dirtyLogPanels = {};
var _logFlushScheduled = false;

function scheduleLogFlush() {
  if (_logFlushScheduled) return;
  _logFlushScheduled = true;
  requestAnimationFrame(flushLogPanels);
}

function flushLogPanels() {
  _logFlushScheduled = false;
  var pending = _dirtyLogPanels;
  _dirtyLogPanels = {};
  for (var panelId in pending) {
    if (!pending.hasOwnProperty(panelId)) continue;
    var el = document.getElementById('log-panel-' + panelId);
    if (!el) continue;
    while (el.childElementCount > LOG_MAX_LINES && el.firstElementChild) {
      el.removeChild(el.firstElementChild);
    }
    el.scrollTop = el.scrollHeight;
  }
}

function writeToPanel(panelId, msg, cls) {
  var el = document.getElementById('log-panel-' + panelId);
  if (!el) return;

  if (!el.childElementCount) {
    el.textContent = '';
  }

  var line = document.createElement('span');
  if (cls) line.className = cls;
  line.textContent = msg + '\n';
  el.appendChild(line);
  _dirtyLogPanels[panelId] = true;
  scheduleLogFlush();
}

function log(msg, cls) {
  writeToPanel('all', msg, cls);
}

var _pollTimer = null;
var _evtSource = null;
var _lastLogSeq = 0;
var _lastExportSeq = 0;
var _lastFailureKey = '';
var _houdiniOpenPollTimer = null;
var _awaitingRun = false;

function reloadGridNow() {
  clearTimeout(gridTimer);
  loadGrid();
}

function pollHoudiniAfterOpen(remaining) {
  clearTimeout(_houdiniOpenPollTimer);
  refreshServiceState();
  if (remaining <= 0) return;
  _houdiniOpenPollTimer = setTimeout(function() {
    pollHoudiniAfterOpen(remaining - 1);
  }, 2000);
}

function pollStatus() {
  fetch('/status')
  .then(r => r.json())
  .then(applyStatus)
  .catch(function() { /* server may be restarting */ });
}

function applySharedStatus(d) {
  updateRunStatusFromHealth(d);
  updateSoftwarePath(d.software_paths);
  updateDccSoftwarePaths(d.software_paths);
  updateExportButton(!!d.export_available, !!d.export_running || !!d.running);
  setHoudiniBadge(!!d.houdini_available, d.houdini_asset);
  updateSelectionButtons(!!d.running);
  if (window.VC_HOUDINI_PREVIEW) window.VC_HOUDINI_PREVIEW.update(d);
}

function applyStatus(d) {
  (function() {
    applySharedStatus(d);

    if (d.log_lines && d.log_lines.length) {
      var logBase = d.log_offset || 0;
      var globalEnd = logBase + d.log_lines.length;
      if (globalEnd > _lastLogSeq) {
        var startIdx = Math.max(_lastLogSeq, logBase) - logBase;
        var newLines = d.log_lines.slice(startIdx);
        for (var i = 0; i < newLines.length; i++) {
          var line = newLines[i];
          var cls = 'dim';
          if (line.indexOf('[OK]') >= 0) cls = 'ok';
          else if (line.indexOf('[ERR]') >= 0 || line.indexOf('[FAIL]') >= 0) cls = 'err';
          else if (line.indexOf('[WARN]') >= 0) cls = 'warn';
          else if (line.match(/^\[[^\]]*\d+\/\d+\]/) || line.indexOf('====') >= 0) cls = 'step';
          else if (line.indexOf('[RUN]') >= 0 || line.indexOf('[INFO]') >= 0) cls = 'info';
          log(line, cls);
        }
        _lastLogSeq = globalEnd;
      }
    }

    if (d.export_log_lines && d.export_log_lines.length) {
      var exportBase = d.export_log_offset || 0;
      var exportEnd = exportBase + d.export_log_lines.length;
      if (exportEnd > _lastExportSeq) {
        var exStartIdx = Math.max(_lastExportSeq, exportBase) - exportBase;
        var exportLines = d.export_log_lines.slice(exStartIdx);
        for (var j = 0; j < exportLines.length; j++) {
          var exLine = exportLines[j];
          var exCls = 'dim';
          if (exLine.indexOf('[OK]') >= 0 || exLine.indexOf(' OK:') >= 0) exCls = 'ok';
          else if (exLine.indexOf('[ERR]') >= 0 || exLine.indexOf('[FAIL]') >= 0) exCls = 'err';
          else if (exLine.indexOf('[WARN]') >= 0) exCls = 'warn';
          log(exLine, exCls);
        }
        _lastExportSeq = exportEnd;
      }
    }
    if (d.export_done && !d.export_running) {
      stopStatusStream();
      refreshServiceState();
      return;
    }

    if (d.done && !d.export_running) {
      stopStatusStream();
      renderStageChecklist(d);
      if (d.ok) {
        var doneLabel = d.operation === 'download' ? '[OK] 数据下载完成' : '[OK] 生成完成';
        var doneLog = d.operation === 'download' ? '[OK] 数据下载完成！区域: ' : '[OK] 生成完成！区域: ';
        setRunStatus('ok', '完成', 100, doneLabel);
        log(doneLog + d.name, 'ok');
        if (d.run_id) log('run_id: ' + d.run_id, 'dim');
        if (d.operation === 'download') {
          reloadGridNow();
        }
        if (d.auto_shutdown_on_success) {
          log('3 秒后自动关闭页面，5 秒后停止本地服务...', 'dim');
          setTimeout(function() {
            window.open('', '_self');
            window.close();
            document.body.innerHTML = '<div style="font-family:Noto Sans SC,Microsoft YaHei,PingFang SC,Segoe UI,Arial,sans-serif;background:var(--base);color:var(--accent);height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column;"><h2>[OK] VirtualCity 生成完成</h2><p>本地服务已自动停止，可以关闭此页面。</p></div>';
          }, 3000);
        } else {
          log('状态服务保持运行，可继续查看 /status 或继续选择网格测试。', 'dim');
          updateSelectionButtons(false);
          scheduleGridLoad();
          refreshServiceState();
        }
      } else {
        var failDetail = failureStatusDetail(d.failure_summary, '[FAIL] 管线出错');
        setRunStatus('off', '失败', d.pct || 0, failDetail);
        setFailureSummary(d.failure_summary);
        logFailureSummary(d.failure_summary, d.returncode);
        updateSelectionButtons(false);
        refreshServiceState();
      }
    }
  })();
}

function submitSelectedArea(mode, actionLabel) {
  if (!selection) return;
  var name = selection.selection_id;
  var b = selection.bbox;
  updateSelectionButtons(true);
  document.getElementById('log-panel-all').innerHTML = '';
  _lastLogSeq = 0;
  _lastExportSeq = 0;
  _lastFailureKey = '';
  _awaitingRun = true;
  setFailureSummary(null);
  setRunStatus('warn', '启动中', 0, actionLabel + ': ' + name);
  log('[' + new Date().toLocaleTimeString() + '] ' + actionLabel + ': ' + name, 'ok');
  log('bbox = [' + b[0]+', '+b[1]+', '+b[2]+', '+b[3]+']', 'dim');
  updateExportButton(false, true);

  fetch('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tile_ids: selection.tiles.map(function(tile) { return tile.tile_id; }),
      mode: mode
    })
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      log(d.message || '任务已启动...', 'dim');
      startStatusStream();
      // 兜底：8 秒内若仍未等到 running，解除等待标志。
      setTimeout(function() { _awaitingRun = false; }, 8000);
    } else {
      _awaitingRun = false;
      log('[错误] ' + d.message, 'err');
      updateSelectionButtons(false);
      refreshServiceState();
    }
  })
  .catch(e => {
    _awaitingRun = false;
    log('[网络错误] ' + e, 'err');
    updateSelectionButtons(false);
    refreshServiceState();
  });
}

function runPipeline() {
  submitSelectedArea('generate', '提交 Houdini 生成');
}

function downloadData() {
  submitSelectedArea('download', '提交数据下载');
}

function stopStatusStream() {
  if (_evtSource) { try { _evtSource.close(); } catch (e) {} _evtSource = null; }
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
}

function startStatusStream() {
  stopStatusStream();
  if (typeof window.EventSource === 'undefined') {
    _pollTimer = setInterval(pollStatus, 1000);
    return;
  }
  try {
    _evtSource = new EventSource('/events');
  } catch (e) {
    _pollTimer = setInterval(pollStatus, 1000);
    return;
  }
  _evtSource.onmessage = function(ev) {
    try { applyStatus(JSON.parse(ev.data)); } catch (e) {}
  };
  _evtSource.onerror = function() {
    if (_evtSource) { try { _evtSource.close(); } catch (e) {} _evtSource = null; }
    if (!_pollTimer) _pollTimer = setInterval(pollStatus, 1000);
  };
}

function ensurePolling() {
  if (!_evtSource && !_pollTimer) startStatusStream();
}

function exportFbx() {
  document.getElementById('export-btn').disabled = true;
  _lastExportSeq = 0;
  setRunStatus('warn', '导出中', 0, 'Houdini 正在导出 FBX');
  log('[' + new Date().toLocaleTimeString() + '] 开始导出 FBX（不触发 UE5 导入）...', 'ok');
  fetch('/export', { method: 'POST' })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.ok) {
      ensurePolling();
    } else {
      log('[错误] ' + d.message, 'err');
      refreshServiceState();
    }
  })
  .catch(function(e) {
    log('[网络错误] ' + e, 'err');
    refreshServiceState();
  });
}
