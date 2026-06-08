"""HTML template for the VirtualCity area picker."""

HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>VirtualCity — 固定网格框选器</title>
<link rel="stylesheet" href="/static/leaflet/leaflet.css"/>
<link rel="stylesheet" href="/static/leaflet-draw/leaflet.draw.css"/>
<style>
:root {
  --surface: #141615;
  --surface-2: #1b1e1c;
  --surface-3: #232724;
  --line: #343a35;
  --line-soft: rgba(255,255,255,0.08);
  --text: #f0f3ef;
  --muted: #aab2aa;
  --subtle: #79837c;
  --teal: #21b6a8;
  --teal-strong: #18a092;
  --green: #7fc36a;
  --amber: #d59b38;
  --red: #e07168;
  --blue: #2f80c8;
  --shadow: 0 18px 45px rgba(0,0,0,0.32);
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  font-family: 'Segoe UI', Arial, sans-serif;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  height: 100vh;
  overflow: hidden;
  background: #0f1110;
  color: var(--text);
}
button, input { font: inherit; }
#toolbar {
  min-height: 64px;
  padding: 10px 18px;
  background: linear-gradient(180deg, #171a18, #111311);
  color: var(--text);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid var(--line);
}
.brand-lockup {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-mark {
  width: 36px;
  height: 36px;
  border: 1px solid rgba(33,182,168,0.48);
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: #dffff9;
  background: linear-gradient(135deg, rgba(33,182,168,0.2), rgba(127,195,106,0.12));
  font-size: 13px;
  font-weight: 800;
}
#toolbar h1 {
  margin: 0;
  font-size: 17px;
  font-weight: 750;
  line-height: 1.15;
}
.brand-copy p {
  margin: 3px 0 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.2;
}
.toolbar-cluster {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  min-width: 0;
}
.version-chip, .status-line {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--muted);
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--line-soft);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
}
.status-line { color: #d3ddd5; }
#workspace {
  position: relative;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(320px, 382px) minmax(0, 1fr) minmax(300px, 326px);
  grid-template-areas: "controls map actions";
  gap: 0;
  background: #080a09;
}
#map-shell {
  grid-area: map;
  position: relative;
  min-height: 0;
  overflow: hidden;
}
#map {
  width: 100%;
  height: 100%;
  min-height: 0;
}
#map .map-tool-control {
  position: absolute;
  left: 14px;
  bottom: 14px;
  z-index: 480;
}
#control-panel {
  grid-area: controls;
  position: relative;
  z-index: 500;
  width: auto;
  min-width: 0;
  height: 100%;
  max-height: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  overflow-y: auto;
  color: var(--text);
  background: var(--surface);
  border: 0;
  border-right: 1px solid var(--line);
  border-radius: 0;
  box-shadow: none;
  backdrop-filter: none;
}
#action-panel {
  grid-area: actions;
  position: relative;
  z-index: 500;
  width: auto;
  min-width: 0;
  height: 100%;
  max-height: none;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 13px;
  overflow-y: auto;
  color: var(--text);
  background: var(--surface);
  border: 0;
  border-left: 1px solid var(--line);
  border-radius: 0;
  box-shadow: none;
  backdrop-filter: none;
}
.action-panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--line-soft);
}
.action-module {
  display: grid;
  gap: 8px;
}
.action-module + .action-module {
  padding-top: 11px;
  border-top: 1px solid var(--line-soft);
}
.action-module-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.action-module-title {
  color: #dfe7df;
  font-size: 12px;
  font-weight: 800;
}
.action-module-state {
  max-width: 104px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #9fcac2;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--line-soft);
  border-radius: 999px;
  padding: 3px 7px;
  font-size: 10.5px;
}
.houdini-status-stack {
  display: grid;
  gap: 7px;
}
.status-row {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 32px;
  padding: 7px 8px;
  background: rgba(255,255,255,0.035);
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}
.status-label {
  color: var(--subtle);
  font-size: 10.5px;
}
.status-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #d7ddd7;
  font-size: 11.5px;
  font-weight: 760;
}
.status-ok .status-value { color: #b9efa9; }
.status-warn .status-value { color: #ffe3a9; }
.status-off .status-value { color: #ffaca6; }
#houdini-badge {
  width: 100%;
  min-height: 34px;
  justify-content: center;
}
.software-path-editor {
  display: block;
  width: 100%;
}
.software-path-editor input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  min-height: 34px;
  padding: 7px 8px;
  color: var(--text);
  background: rgba(255,255,255,0.035);
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  font-size: 11.5px;
  line-height: 1.35;
  outline: none;
}
.software-path-editor input:focus {
  border-color: rgba(33,182,168,0.65);
}
.software-path-note {
  min-height: 14px;
  color: var(--subtle);
  font-size: 10.5px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.run-status-panel {
  display: grid;
  gap: 8px;
  padding: 9px;
  background: rgba(255,255,255,0.035);
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}
.run-status-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.run-state {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #d7ddd7;
  font-size: 12px;
  font-weight: 800;
}
.run-pct {
  color: #9fcac2;
  font-family: Consolas, 'Cascadia Mono', monospace;
  font-size: 11px;
  font-weight: 800;
}
.run-progress-track {
  position: relative;
  height: 8px;
  overflow: hidden;
  background: #080a09;
  border: 1px solid var(--line);
  border-radius: 999px;
}
.run-progress-bar {
  width: 0%;
  height: 100%;
  background: linear-gradient(90deg, #137e75, #21b6a8);
  border-radius: 999px;
  transition: width 0.3s ease, background 0.2s ease;
}
.run-status-detail {
  min-height: 16px;
  color: var(--subtle);
  font-size: 11px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.failure-summary {
  display: grid;
  gap: 4px;
  padding-top: 2px;
}
.failure-summary[hidden] {
  display: none;
}
.failure-row {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
  font-size: 10.5px;
  line-height: 1.3;
}
.failure-key {
  color: var(--subtle);
  font-weight: 750;
}
.failure-value {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #d7ddd7;
}
.failure-row.reason .failure-value {
  color: #ffaca6;
}
.failure-row.metrics .failure-value {
  color: #ffe3a9;
}
.run-status-panel.status-ok .run-state,
.run-status-panel.status-ok .run-pct {
  color: #b9efa9;
}
.run-status-panel.status-off .run-state,
.run-status-panel.status-off .run-pct {
  color: #ffaca6;
}
.run-status-panel.status-warn .run-state,
.run-status-panel.status-warn .run-pct {
  color: #ffe3a9;
}
.panel-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line-soft);
}
.panel-section:last-child {
  padding-bottom: 0;
  border-bottom: none;
}
.section-row, .selection-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.section-kicker {
  color: #dfe7df;
  font-size: 13px;
  font-weight: 750;
}
.section-note {
  margin-top: 3px;
  color: var(--subtle);
  font-size: 11px;
}
#area-id-chip {
  display: inline-flex;
  align-items: center;
  max-width: 250px;
  min-height: 28px;
  padding: 5px 9px;
  color: #dbfff9;
  background: rgba(33,182,168,0.14);
  border: 1px solid rgba(33,182,168,0.26);
  border-radius: 999px;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
#tile-display {
  min-height: 74px;
  margin-top: 10px;
  padding: 10px;
  color: #c7f3e9;
  background: #0d0f0e;
  border: 1px solid var(--line);
  border-radius: 6px;
  font-family: Consolas, 'Cascadia Mono', monospace;
  font-size: 11.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.metric-grid {
  display: grid;
  grid-template-columns: minmax(96px, 0.75fr) minmax(0, 1.25fr);
  gap: 8px;
}
.metric {
  min-height: 52px;
  padding: 8px 10px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.metric-label {
  display: block;
  color: var(--subtle);
  font-size: 10.5px;
}
.metric-value {
  display: block;
  margin-top: 4px;
  color: var(--text);
  font-size: 15px;
  font-weight: 760;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.metric-wide {
  grid-column: auto;
}
.metric-wide .metric-value {
  font-family: Consolas, 'Cascadia Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  white-space: normal;
  overflow-wrap: anywhere;
}
.data-overview {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--line-soft);
}
.data-overview .section-row {
  align-items: center;
}
.data-overview .filter {
  margin-left: auto;
}
.source-list {
  display: grid;
  gap: 8px;
  margin-top: 8px;
}
.source-card {
  padding: 9px 10px;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--line-soft);
  border-radius: 6px;
}
.source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.source-title {
  color: var(--text);
  font-size: 12px;
  font-weight: 800;
}
.source-state {
  max-width: 128px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #dffdf7;
  background: rgba(33,182,168,0.12);
  border: 1px solid rgba(33,182,168,0.24);
  border-radius: 999px;
  padding: 3px 7px;
  font-size: 10.5px;
}
.source-provider {
  margin-top: 6px;
  color: #d9e2d9;
  font-size: 12px;
  line-height: 1.35;
}
.source-detail {
  margin-top: 3px;
  color: var(--subtle);
  font-size: 11px;
  line-height: 1.35;
}
.source-file {
  margin-top: 5px;
  color: #91cfc6;
  font-family: Consolas, 'Cascadia Mono', monospace;
  font-size: 10.5px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.source-action-btn {
  min-width: 112px;
  min-height: 44px;
  padding: 7px 9px;
  color: #041614;
  background: #c6d6d2;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
}
.source-action-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.04);
}
.source-action-btn:disabled {
  color: #818982;
  background: rgba(255,255,255,0.06);
  border-color: var(--line-soft);
  cursor: not-allowed;
}
.source-action-btn .btn-main {
  font-size: 12px;
}
.source-action-btn .btn-sub {
  font-size: 10px;
  color: rgba(4,22,20,0.72);
}
.source-action-btn:disabled .btn-sub {
  color: #646d66;
}
.filter {
  min-height: 34px;
  color: var(--text);
  font-size: 12px;
  display: inline-flex;
  gap: 8px;
  align-items: center;
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  padding: 6px 9px;
  white-space: nowrap;
}
.filter input {
  width: 15px;
  height: 15px;
  accent-color: var(--teal);
}
.badge {
  min-height: 32px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  white-space: nowrap;
  border: 1px solid transparent;
  cursor: pointer;
  font-family: inherit;
  font-weight: 700;
}
.badge-ok {
  background: rgba(127,195,106,0.16);
  border-color: rgba(127,195,106,0.36);
  color: #d9f7ce;
}
.badge-warn {
  background: rgba(213,155,56,0.16);
  border-color: rgba(213,155,56,0.38);
  color: #ffe3a9;
}
.badge:hover:not(:disabled) { filter: brightness(1.12); }
.badge:disabled { opacity: 0.78; cursor: wait; }
.action-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.action-btn {
  min-height: 56px;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  color: #041614;
  background: var(--teal);
  transition: transform 0.15s ease, filter 0.15s ease, background 0.15s ease;
}
.action-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.06);
}
.action-btn:disabled {
  color: #818982;
  background: rgba(255,255,255,0.06);
  border-color: var(--line-soft);
  cursor: not-allowed;
}
.btn-main {
  display: block;
  font-size: 14px;
  line-height: 1.2;
  font-weight: 800;
}
.btn-sub {
  display: block;
  margin-top: 4px;
  color: rgba(4,22,20,0.74);
  font-size: 11px;
  line-height: 1.25;
}
.action-btn:disabled .btn-sub { color: #646d66; }
.placeholder-btn,
.placeholder-btn:disabled {
  color: #737c75;
  background: rgba(255,255,255,0.035);
  border-color: var(--line-soft);
  cursor: not-allowed;
}
.placeholder-btn .btn-sub,
.placeholder-btn:disabled .btn-sub {
  color: #5f6861;
}
#export-btn { background: var(--amber); }
#download-btn { background: #c6d6d2; }
#run-btn:disabled,
#export-btn:disabled,
#download-btn:disabled {
  color: #818982;
  background: rgba(255,255,255,0.06);
  border-color: var(--line-soft);
  cursor: not-allowed;
}
#run-btn:disabled .btn-sub,
#export-btn:disabled .btn-sub,
#download-btn:disabled .btn-sub {
  color: #646d66;
}
#legend {
  position: absolute;
  z-index: 450;
  right: 12px;
  bottom: 12px;
  background: rgba(20,22,21,0.92);
  color: #e5ebe5;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 8px;
  padding: 9px 11px;
  font-size: 12px;
  line-height: 1.7;
  box-shadow: 0 10px 28px rgba(0,0,0,0.22);
}
.swatch {
  display: inline-block;
  width: 18px;
  height: 12px;
  margin-right: 7px;
  vertical-align: -1px;
  border: 1px solid #87908a;
}
.swatch-empty { background: transparent; border-color: var(--blue); }
.swatch-dim { background: rgba(6,8,7,0.62); border-color: #232724; }
.leaflet-control-zoom {
  display: none;
}
.map-tool-control {
  flex: 0 0 auto;
  display: flex;
  overflow: hidden;
  background: #0d0f0e;
  border: 1px solid var(--line);
  border-radius: 6px;
  box-shadow: none;
}
.map-tool-control button {
  position: relative;
  width: 33px;
  height: 31px;
  display: grid;
  place-items: center;
  border: 0;
  border-right: 1px solid var(--line);
  background: #0d0f0e;
  color: #f2f6f1;
  cursor: pointer;
}
.map-tool-control button:last-child {
  border-right: 0;
}
.map-tool-control button:hover:not(:disabled),
.map-tool-control button.active {
  background: #1b1e1c;
  color: #ffffff;
}
.map-tool-control button:disabled {
  cursor: default;
  opacity: 0.46;
}
.tool-icon {
  width: 18px;
  height: 18px;
  display: block;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
  fill: none;
}
.point-select-active,
.point-select-active .leaflet-tile {
  cursor: crosshair;
}
.leaflet-touch .leaflet-bar a {
  width: 32px;
  height: 32px;
  line-height: 32px;
}
#progress-container {
  display: none;
  padding: 10px 18px;
  background: #111311;
  border-top: 1px solid var(--line);
}
#progress-bar-wrap {
  background: #080a09;
  border-radius: 6px;
  height: 22px;
  overflow: hidden;
  border: 1px solid var(--line);
  position: relative;
}
#progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #137e75, #21b6a8);
  border-radius: 6px;
  transition: width 0.4s ease;
  box-shadow: 0 0 10px rgba(33,182,168,0.36);
}
#progress-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 800;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0,0,0,0.55);
}
#step-label {
  color: #bfeee7;
  font-size: 12px;
  margin-top: 6px;
}
#console-dock {
  min-height: 166px;
  background: #080a09;
  border-top: 1px solid var(--line);
}
#log-tabs {
  background: #111311;
  display: flex;
  align-items: flex-end;
  gap: 4px;
  padding: 6px 10px 0 10px;
  border-bottom: 1px solid var(--line);
}
.tab-btn {
  min-height: 32px;
  background: transparent;
  border: 1px solid transparent;
  color: #8e9991;
  font-family: inherit;
  font-size: 12px;
  font-weight: 750;
  padding: 7px 12px;
  cursor: pointer;
  border-radius: 6px 6px 0 0;
  border-bottom: none;
  transition: background 0.15s ease, color 0.15s ease;
}
.tab-btn:hover {
  color: #c5d0c7;
  background: rgba(255,255,255,0.05);
}
.tab-btn.active {
  color: #dffdf7;
  border-color: var(--line);
  background: #080a09;
}
.log-panel {
  height: 132px;
  background: #080a09;
  color: #92d5ca;
  font-family: Consolas, 'Cascadia Mono', monospace;
  font-size: 11.5px;
  line-height: 1.45;
  padding: 9px 14px;
  overflow-y: auto;
  white-space: pre-wrap;
}
.ok  { color: #b9efa9; }
.err { color: #ffaca6; }
.dim { color: #7f8a83; }
.step { color: #7cd9cd; font-weight: 800; }
@media (max-width: 980px) {
  body {
    height: auto;
    min-height: 100vh;
    overflow: auto;
    display: flex;
    flex-direction: column;
  }
  #toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
  .toolbar-cluster {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: wrap;
  }
  #workspace {
    min-height: 680px;
    display: flex;
    flex-direction: column;
    overflow: visible;
  }
  #map-shell {
    position: relative;
    order: 3;
    height: 520px;
    min-height: 520px;
  }
  #map {
    min-height: 520px;
  }
  #control-panel {
    position: relative;
    order: 1;
    inset: auto;
    width: auto;
    max-height: none;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }
  #action-panel {
    position: relative;
    order: 2;
    inset: auto;
    width: auto;
    max-height: none;
    height: auto;
    border-left: 0;
    border-bottom: 1px solid var(--line);
  }
  #legend {
    right: 12px;
    bottom: 12px;
  }
}
@media (max-width: 560px) {
  .metric-grid, .action-grid {
    grid-template-columns: 1fr;
  }
  .data-overview .section-row {
    display: grid;
    grid-template-columns: 1fr;
  }
  .data-overview .filter {
    width: 100%;
    justify-content: center;
    margin-left: 0;
  }
  .panel-section .section-row {
    flex-wrap: wrap;
    align-items: flex-start;
  }
  .source-action-btn {
    width: 100%;
  }
  .version-chip, .status-line {
    max-width: 100%;
  }
  #console-dock { min-height: 190px; }
  .log-panel { height: 150px; }
}
</style>
</head>
<body>
<div id="toolbar">
  <div class="brand-lockup">
    <div class="brand-mark">VC</div>
    <div class="brand-copy">
      <h1>CityEngine</h1>
      <p>固定 1km UTM 网格 · 数据缓存 · Houdini 构建</p>
    </div>
  </div>
  <div class="toolbar-cluster">
    <span class="version-chip">__VERSION__</span>
  </div>
</div>
<main id="workspace">
  <div id="map-shell">
    <div id="map">
      <div id="legend">
        <div><span class="swatch swatch-dim"></span>未缓存：整体压暗</div>
        <div><span class="swatch swatch-empty"></span>已缓存：无填充</div>
      </div>
      <div id="selection-tools" class="map-tool-control" aria-label="区域选择工具">
        <!-- Icons: Lucide, ISC license. -->
        <button type="button" class="map-tool-button map-tool-rectangle" title="框选网格" aria-label="框选网格">
          <svg class="tool-icon" aria-hidden="true" viewBox="0 0 24 24">
            <rect width="18" height="18" x="3" y="3" rx="2"></rect>
          </svg>
        </button>
        <button type="button" class="map-tool-button map-tool-point" title="点选网格" aria-label="点选网格">
          <svg class="tool-icon" aria-hidden="true" viewBox="0 0 24 24">
            <path d="M4.037 4.688a.495.495 0 0 1 .651-.651l16 6.5a.5.5 0 0 1-.063.947l-6.124 1.58a2 2 0 0 0-1.438 1.435l-1.579 6.126a.5.5 0 0 1-.947.063z"></path>
          </svg>
        </button>
        <button type="button" class="map-tool-button map-tool-clear" title="清空选择" aria-label="清空选择" disabled>
          <svg class="tool-icon" aria-hidden="true" viewBox="0 0 24 24">
            <path d="M10 11v6"></path>
            <path d="M14 11v6"></path>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path>
            <path d="M3 6h18"></path>
            <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
        </button>
      </div>
    </div>
  </div>
  <aside id="control-panel" aria-label="区域操作面板">
    <section class="panel-section">
      <div class="selection-title-row">
        <div>
          <div class="section-kicker">区域选择</div>
          <div class="section-note">连续矩形网格块</div>
        </div>
      </div>
      <div id="area-id-chip">未选择区域</div>
      <div id="tile-display">尚未框选网格</div>
      <div class="data-overview">
        <div class="section-row">
          <div>
            <div class="section-kicker">视口数据</div>
            <div id="grid-status" class="section-note">加载网格中...</div>
          </div>
        </div>
        <div class="metric-grid">
          <div class="metric">
            <span class="metric-label">完整数据区域</span>
            <span id="downloaded-area-count" class="metric-value">--</span>
          </div>
          <div class="metric metric-wide">
            <span class="metric-label">BBox</span>
            <span id="selection-bbox" class="metric-value">--</span>
          </div>
        </div>
      </div>
    </section>
    <section class="panel-section">
      <div class="section-row">
        <div>
          <div class="section-kicker">数据源</div>
          <div id="source-status" class="section-note">读取当前区域数据源...</div>
        </div>
        <button id="download-btn" disabled onclick="downloadData()" class="source-action-btn">
          <span class="btn-main">下载地图数据</span>
          <span class="btn-sub">OSM / DEM / 建筑</span>
        </button>
      </div>
      <div id="source-list" class="source-list">
        <div class="source-card">
          <div class="source-head">
            <span class="source-title">道路</span>
            <span class="source-state">读取中</span>
          </div>
          <div class="source-provider">OpenStreetMap</div>
          <div class="source-detail">OSM highway ways</div>
          <div class="source-file">--</div>
        </div>
        <div class="source-card">
          <div class="source-head">
            <span class="source-title">建筑</span>
            <span class="source-state">读取中</span>
          </div>
          <div class="source-provider">Overture Maps + Google Open Buildings</div>
          <div class="source-detail">建筑轮廓 + 高度补全</div>
          <div class="source-file">--</div>
        </div>
        <div class="source-card">
          <div class="source-head">
            <span class="source-title">地形</span>
            <span class="source-state">读取中</span>
          </div>
          <div class="source-provider">FABDEM / NASADEM</div>
          <div class="source-detail">DEM CSV</div>
          <div class="source-file">--</div>
        </div>
      </div>
    </section>
  </aside>
  <aside id="action-panel" aria-label="执行操作面板">
    <div class="action-panel-head">
      <div>
        <div class="section-kicker">执行工作流</div>
        <div class="section-note">当前框选区域</div>
      </div>
    </div>
    <section class="action-module" aria-label="数据处理">
      <div class="action-module-head">
        <div class="action-module-title">数据处理</div>
        <div class="action-module-state">数据准备</div>
      </div>
      <div class="action-grid">
        <button type="button" disabled class="action-btn placeholder-btn" title="建筑数据清洗入口待接入">
          <span class="btn-main">建筑</span>
          <span class="btn-sub">待接入</span>
        </button>
        <button type="button" disabled class="action-btn placeholder-btn" title="地形数据清洗入口待接入">
          <span class="btn-main">地形</span>
          <span class="btn-sub">待接入</span>
        </button>
        <button type="button" disabled class="action-btn placeholder-btn" title="自然数据处理入口待接入">
          <span class="btn-main">自然</span>
          <span class="btn-sub">待接入</span>
        </button>
        <button type="button" disabled class="action-btn placeholder-btn" title="道路数据处理入口待接入">
          <span class="btn-main">道路</span>
          <span class="btn-sub">待接入</span>
        </button>
      </div>
    </section>
    <section class="action-module" aria-label="软件链接">
      <div class="action-module-head">
        <div class="action-module-title">软件链接</div>
        <div class="action-module-state">本地会话</div>
      </div>
      <div class="houdini-status-stack" aria-label="Houdini 状态">
        <div class="software-path-editor">
          <input id="houdini-path-input" type="text" spellcheck="false" placeholder="输入 Houdini 软件路径，例如 D:\houdini21\bin\houdini.exe">
        </div>
        <div id="houdini-path-note" class="software-path-note">未设置软件路径</div>
        <button id="houdini-badge" type="button" class="badge badge-warn" onclick="openOrProbeHoudini()" title="未连接时启动路径里的 Houdini；已连接时刷新状态">打开 Houdini</button>
        <div id="houdini-connection-row" class="status-row status-warn">
          <span class="status-label">软件连接</span>
          <span id="houdini-connection-value" class="status-value">待检查</span>
        </div>
        <div id="houdini-asset-row" class="status-row status-warn">
          <span class="status-label">模型资产</span>
          <span id="houdini-asset-value" class="status-value">等待生成</span>
        </div>
        <div id="houdini-export-row" class="status-row status-warn">
          <span class="status-label">导出就绪</span>
          <span id="houdini-export-value" class="status-value">等待资产</span>
        </div>
      </div>
      <div class="action-grid">
        <button id="run-btn" disabled onclick="runPipeline()" class="action-btn">
          <span class="btn-main">Houdini 生成</span>
          <span class="btn-sub">完整构建 + QA</span>
        </button>
        <button id="export-btn" disabled onclick="exportFbx()" class="action-btn">
          <span class="btn-main">导出 FBX</span>
          <span class="btn-sub">审核后资产</span>
        </button>
      </div>
    </section>
    <section class="action-module" aria-label="执行状态">
      <div class="action-module-head">
        <div class="action-module-title">执行状态</div>
        <div id="run-status-chip" class="action-module-state">待命</div>
      </div>
      <div id="run-status-panel" class="run-status-panel status-warn">
        <div class="run-status-head">
          <div id="run-status-title" class="run-state">等待选择区域</div>
          <div id="run-status-pct" class="run-pct">0%</div>
        </div>
        <div class="run-progress-track" aria-label="执行进度">
          <div id="run-status-bar" class="run-progress-bar"></div>
        </div>
        <div id="run-status-detail" class="run-status-detail">尚未启动任务</div>
        <div id="failure-summary" class="failure-summary" hidden>
          <div class="failure-row reason">
            <span class="failure-key">原因</span>
            <span id="failure-reason" class="failure-value">--</span>
          </div>
          <div class="failure-row report">
            <span class="failure-key">报告</span>
            <span id="failure-report" class="failure-value">--</span>
          </div>
          <div class="failure-row metrics">
            <span class="failure-key">指标</span>
            <span id="failure-metrics" class="failure-value">--</span>
          </div>
        </div>
      </div>
    </section>
  </aside>
</main>
<div id="progress-container">
  <div id="progress-bar-wrap">
    <div id="progress-bar" style="width:0%"></div>
    <div id="progress-text">0%</div>
  </div>
  <div id="step-label">准备中...</div>
</div>
<div id="console-dock">
  <div id="log-tabs">
    <button class="tab-btn active" onclick="switchTab('all')">完整控制台</button>
    <button class="tab-btn" onclick="switchTab('clean')">离线精炼</button>
    <button class="tab-btn" onclick="switchTab('houdini')">Houdini 算子</button>
    <button class="tab-btn" onclick="switchTab('qa')">QA 质量审查</button>
  </div>
  <div id="log-panels-container">
    <div id="log-panel-all" class="log-panel">等待选择网格...</div>
    <div id="log-panel-clean" class="log-panel" style="display:none">等待数据下载或精炼...</div>
    <div id="log-panel-houdini" class="log-panel" style="display:none">等待 Houdini RPYC 执行...</div>
    <div id="log-panel-qa" class="log-panel" style="display:none">等待 Model QA 诊断报告...</div>
  </div>
</div>

<script src="/static/leaflet/leaflet.js"></script>
<script src="/static/leaflet-draw/leaflet.draw.js"></script>
<script>
var selection = null;
var selectedTileIds = {};
var lastGridData = null;
var gridLayer = null;
var drawnItems = null;
var gridRequestId = 0;
var gridTimer = null;
var maxSelectionTiles = __MAX_SELECTION_TILES__;
var shutdownWithPage = __SHUTDOWN_WITH_PAGE__;
var pageSessionTimer = null;
var selectionStorageKey = 'vc.areaPicker.selection.v1';
var pendingRestoreTileIds = null;
var pendingRestoreLogged = false;
var rectangleDrawTool = null;
var pointSelectActive = false;
var selectionToolButtons = {};

var map = L.map('map', { zoomControl: false }).setView([__LAT__, __LON__], 14);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors', maxZoom: 19
}).addTo(map);
gridLayer = L.layerGroup().addTo(map);
drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

rectangleDrawTool = new L.Draw.Rectangle(map, {
  shapeOptions: { color: '#ffeb3b', weight: 2, fillOpacity: 0.02 }
});

function rectangleToolActive() {
  return !!(rectangleDrawTool && rectangleDrawTool.enabled && rectangleDrawTool.enabled());
}

function updateMapToolButtons() {
  if (selectionToolButtons.rectangle) {
    selectionToolButtons.rectangle.classList.toggle('active', rectangleToolActive());
  }
  if (selectionToolButtons.point) {
    selectionToolButtons.point.classList.toggle('active', pointSelectActive);
  }
  if (selectionToolButtons.clear) {
    selectionToolButtons.clear.disabled = !selection;
  }
}

function setPointSelectActive(active) {
  pointSelectActive = !!active;
  if (pointSelectActive && rectangleToolActive()) rectangleDrawTool.disable();
  var method = pointSelectActive ? 'addClass' : 'removeClass';
  L.DomUtil[method](map.getContainer(), 'point-select-active');
  updateMapToolButtons();
}

function activateRectangleTool() {
  setPointSelectActive(false);
  if (rectangleDrawTool && !rectangleToolActive()) rectangleDrawTool.enable();
  updateMapToolButtons();
}

function clearSelectionFromMapTool() {
  setPointSelectActive(false);
  if (rectangleToolActive()) rectangleDrawTool.disable();
  clearSelection();
}

function bindSelectionTools() {
  selectionToolButtons = {
    rectangle: document.querySelector('.map-tool-rectangle'),
    point: document.querySelector('.map-tool-point'),
    clear: document.querySelector('.map-tool-clear')
  };
  if (selectionToolButtons.rectangle) {
    selectionToolButtons.rectangle.addEventListener('click', activateRectangleTool);
  }
  if (selectionToolButtons.point) {
    selectionToolButtons.point.addEventListener('click', function() {
      setPointSelectActive(!pointSelectActive);
    });
  }
  if (selectionToolButtons.clear) {
    selectionToolButtons.clear.addEventListener('click', clearSelectionFromMapTool);
  }
  updateMapToolButtons();
}
bindSelectionTools();

map.on(L.Draw.Event.CREATED, function(e) {
  drawnItems.clearLayers();
  e.layer.setStyle({ opacity: 0, fillOpacity: 0 });
  drawnItems.addLayer(e.layer);
  selectTilesByBounds(e.layer.getBounds());
});

map.on(L.Draw.Event.DRAWSTART, function() {
  setPointSelectActive(false);
  updateMapToolButtons();
});

map.on(L.Draw.Event.DRAWSTOP, function() {
  updateMapToolButtons();
});

map.on('click', function(e) {
  if (!pointSelectActive) return;
  selectTileByLatLng(e.latlng);
});
document.getElementById('houdini-path-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    saveSoftwarePath(false);
  }
});
document.getElementById('houdini-path-input').addEventListener('blur', function() {
  saveSoftwarePath(false);
});

function setStatusRow(rowId, valueId, state, text, title) {
  var row = document.getElementById(rowId);
  var value = document.getElementById(valueId);
  if (!row || !value) return;
  row.className = 'status-row status-' + state;
  value.textContent = text;
  row.title = title || text;
}

function updateSoftwarePath(paths) {
  var input = document.getElementById('houdini-path-input');
  var note = document.getElementById('houdini-path-note');
  if (!input || !note || !paths) return;
  var value = paths.houdini_exe || '';
  if (document.activeElement !== input) {
    input.value = value;
  }
  if (!value) {
    note.textContent = '未设置软件路径';
    note.style.color = '';
  } else if (paths.houdini_exe_exists) {
    note.textContent = '已设置: ' + value;
    note.style.color = '#b9efa9';
  } else {
    note.textContent = '文件不存在: ' + value;
    note.style.color = '#ffe3a9';
  }
}

function saveSoftwarePath(refreshAfter) {
  var input = document.getElementById('houdini-path-input');
  var note = document.getElementById('houdini-path-note');
  if (!input) return Promise.resolve({ ok: false });
  return fetch('/software-paths', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ houdini_exe: input.value || '' })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) updateSoftwarePath(d.software_paths);
    if (!d.ok && note) {
      note.textContent = d.message || '保存失败';
      note.style.color = '#ffaca6';
    }
    if (refreshAfter) refreshServiceState();
    return d;
  })
  .catch(function(e) {
    if (note) {
      note.textContent = '保存失败: ' + e;
      note.style.color = '#ffaca6';
    }
    return { ok: false, message: String(e) };
  });
}

function setHoudiniBadge(available, asset) {
  var el = document.getElementById('houdini-badge');
  el.disabled = false;
  if (available) {
    el.className = 'badge badge-ok';
    el.textContent = 'Houdini 已连接';
    el.title = 'Houdini 已打开并可连接；点击刷新状态';
  } else {
    el.className = 'badge badge-warn';
    el.textContent = '打开 Houdini';
    el.title = '启动输入路径里的 Houdini';
  }
  updateHoudiniStatusPanel(available, asset || null);
}

function setHoudiniChecking(text) {
  var el = document.getElementById('houdini-badge');
  el.className = 'badge badge-warn';
  el.textContent = text || '处理中...';
  el.disabled = true;
  setStatusRow('houdini-connection-row', 'houdini-connection-value', 'warn', '处理中', '正在处理 Houdini 连接');
}

function openOrProbeHoudini() {
  var badge = document.getElementById('houdini-badge');
  var connected = badge && badge.classList.contains('badge-ok');
  if (connected) {
    setHoudiniChecking('刷新中...');
    refreshServiceState();
    return;
  }
  setHoudiniChecking('启动中...');
  saveSoftwarePath(false).then(function() {
    var input = document.getElementById('houdini-path-input');
    return fetch('/open-houdini', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ houdini_exe: input ? input.value : '' })
    });
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) updateSoftwarePath(d.software_paths);
    if (!d.ok) {
      var note = document.getElementById('houdini-path-note');
      if (note) {
        note.textContent = d.message || '启动失败';
        note.style.color = '#ffaca6';
      }
      refreshServiceState();
      return;
    }
    pollHoudiniAfterOpen(8);
  })
  .catch(function(e) {
    var note = document.getElementById('houdini-path-note');
    if (note) {
      note.textContent = '启动失败: ' + e;
      note.style.color = '#ffaca6';
    }
    refreshServiceState();
  });
}
function updateExportButton(available, running) {
  var btn = document.getElementById('export-btn');
  btn.disabled = !available || !!running;
}

function setRunStatus(state, title, pct, detail) {
  var panel = document.getElementById('run-status-panel');
  var chip = document.getElementById('run-status-chip');
  var titleEl = document.getElementById('run-status-title');
  var pctEl = document.getElementById('run-status-pct');
  var bar = document.getElementById('run-status-bar');
  var detailEl = document.getElementById('run-status-detail');
  if (!panel || !chip || !titleEl || !pctEl || !bar || !detailEl) return;
  var n = Math.max(0, Math.min(100, Number(pct) || 0));
  panel.className = 'run-status-panel status-' + state;
  chip.textContent = title;
  titleEl.textContent = title;
  pctEl.textContent = n + '%';
  bar.style.width = n + '%';
  if (state === 'ok') {
    bar.style.background = 'linear-gradient(90deg, #2e7d32, #a5d6a7)';
  } else if (state === 'off') {
    bar.style.background = 'linear-gradient(90deg, #9f2f28, #e07168)';
  } else if (state === 'warn') {
    bar.style.background = 'linear-gradient(90deg, #a16a1c, #d59b38)';
  } else {
    bar.style.background = 'linear-gradient(90deg, #137e75, #21b6a8)';
  }
  detailEl.textContent = detail || '等待任务';
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
  if (!d) {
    setRunStatus('warn', '待命', 0, '等待选择区域');
    setFailureSummary(null);
    return;
  }
  if (d.running) {
    setRunStatus('warn', '运行中', d.pct || 0, d.step_label || '任务执行中');
    setFailureSummary(null);
  } else if (d.export_running) {
    setRunStatus('warn', '导出中', 0, 'Houdini 正在导出 FBX');
    setFailureSummary(null);
  } else if (d.done) {
    if (d.ok) {
      setRunStatus('ok', '完成', 100, d.step_label || d.name || '任务结束');
      setFailureSummary(null);
    } else {
      setRunStatus('off', '失败', d.pct || 0, failureStatusDetail(d.failure_summary, d.step_label || d.name || '任务失败'));
      setFailureSummary(d.failure_summary);
    }
  } else if (d.failure_summary && d.failure_summary.available) {
    setRunStatus('off', '上次失败', d.pct || 0, failureStatusDetail(d.failure_summary, '上次管线失败'));
    setFailureSummary(d.failure_summary);
  } else {
    setRunStatus('warn', '待命', 0, selection ? '已选择区域，等待执行' : '等待选择区域');
    setFailureSummary(null);
  }
}

function updateHoudiniStatusPanel(available, asset) {
  setStatusRow(
    'houdini-connection-row',
    'houdini-connection-value',
    available ? 'ok' : 'off',
    available ? '在线' : '离线',
    available ? 'Houdini RPYC 已连接' : '需要先打开 Houdini 并启用 RPYC 18811'
  );
  var qaOk = !!(asset && asset.qa_ok);
  var modelReady = !!(asset && asset.model_ready);
  var exportReady = !!(asset && asset.export_ready);
  var message = asset && asset.message ? asset.message : '';
  var assetText = '等待生成';
  var assetState = 'warn';
  if (!available) {
    assetText = '等待 Houdini';
    assetState = 'off';
  } else if (qaOk && modelReady) {
    assetText = 'QA 通过 / 现场可用';
    assetState = 'ok';
  } else if (qaOk && !modelReady) {
    assetText = 'QA 通过 / 现场缺失';
    assetState = 'warn';
  } else if (message.indexOf('run mismatch') >= 0) {
    assetText = 'QA 记录不匹配';
    assetState = 'warn';
  } else if (message.indexOf('area mismatch') >= 0) {
    assetText = '区域不匹配';
    assetState = 'warn';
  } else if (asset && asset.status === 'completed') {
    assetText = 'QA 已完成 / 待确认';
    assetState = 'warn';
  } else if (asset && asset.status) {
    assetText = 'QA ' + asset.status;
    assetState = 'warn';
  }
  setStatusRow(
    'houdini-asset-row',
    'houdini-asset-value',
    assetState,
    assetText,
    message || 'Houdini 生成完成并通过 QA 后，模型资产会进入可导出状态'
  );
  setStatusRow(
    'houdini-export-row',
    'houdini-export-value',
    exportReady ? 'ok' : 'warn',
    exportReady ? '可导出' : '等待资产',
    exportReady ? '当前 Houdini 模型可导出 FBX' : '需要 Houdini 在线、Model QA 通过，并且 OUT_city 现场几何可用'
  );
}

function updateSelectionButtons(running) {
  var disabled = !selection || !!running;
  document.getElementById('run-btn').disabled = disabled;
  document.getElementById('download-btn').disabled = disabled;
}

function updateDownloadedAreaCount(payload) {
  var el = document.getElementById('downloaded-area-count');
  if (!el) return;
  var count = payload && payload.downloaded_areas ? Number(payload.downloaded_areas.count) : NaN;
  el.textContent = Number.isFinite(count) ? (count + ' 个') : '--';
}

function renderDataSources(payload) {
  var status = document.getElementById('source-status');
  var list = document.getElementById('source-list');
  if (!status || !list) return;
  if (!payload || !payload.available) {
    status.textContent = payload && payload.message ? payload.message : '数据源状态不可用';
    return;
  }
  status.textContent = payload.area_id ? ('当前区域: ' + payload.area_id) : '当前区域数据源';
  list.innerHTML = '';
  (payload.items || []).forEach(function(item) {
    var card = document.createElement('div');
    card.className = 'source-card';

    var head = document.createElement('div');
    head.className = 'source-head';
    var title = document.createElement('span');
    title.className = 'source-title';
    title.textContent = item.title || item.key || '数据';
    var state = document.createElement('span');
    state.className = 'source-state';
    var file = item.file || {};
    state.textContent = file.exists ? '已就绪' : '缺失';
    state.title = item.current || '';
    head.appendChild(title);
    head.appendChild(state);

    var provider = document.createElement('div');
    provider.className = 'source-provider';
    provider.textContent = item.provider || '--';

    var detail = document.createElement('div');
    detail.className = 'source-detail';
    detail.textContent = (item.current || item.strategy || '--') + ' · ' + (item.method || '--');

    var fileLine = document.createElement('div');
    fileLine.className = 'source-file';
    fileLine.textContent = (file.exists ? '[OK] ' : '[缺失] ') + (file.path || '--') +
      (file.size_label ? ' · ' + file.size_label : '');
    fileLine.title = file.abs_path || file.path || '';

    card.appendChild(head);
    card.appendChild(provider);
    card.appendChild(detail);
    card.appendChild(fileLine);
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
    setHoudiniBadge(!!d.houdini_available, d.houdini_asset);
    updateSoftwarePath(d.software_paths);
    updateExportButton(!!d.export_available, !!d.running);
    updateSelectionButtons(!!d.running);
    updateDownloadedAreaCount(d);
    updateRunStatusFromHealth(d);
    refreshDataSources();
  })
  .catch(function() {
    setHoudiniBadge(false, null);
    setRunStatus('off', '离线', 0, '状态服务不可用');
  });
}

function probeHoudini() {
  openOrProbeHoudini();
}

function touchPageSession() {
  if (!shutdownWithPage) return;
  fetch('/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    keepalive: true
  }).catch(function() {});
}

function notifyPageClosed() {
  if (!shutdownWithPage) return;
  if (pageSessionTimer) clearInterval(pageSessionTimer);
  var payload = new Blob(['{}'], { type: 'application/json' });
  if (navigator.sendBeacon) {
    navigator.sendBeacon('/session/closed', payload);
  } else {
    fetch('/session/closed', { method: 'POST', body: '{}', keepalive: true }).catch(function() {});
  }
}

function startPageSession() {
  if (!shutdownWithPage) return;
  touchPageSession();
  pageSessionTimer = setInterval(touchPageSession, 2000);
  window.addEventListener('pagehide', notifyPageClosed);
}

function tileStyle(tile) {
  var isSelected = !!selectedTileIds[tile.tile_id];
  var isCached = !!tile.cached;
  return {
    color: isSelected ? '#f3cf4a' : (isCached ? '#2f80c8' : '#252b28'),
    weight: isSelected ? 3 : 1,
    opacity: isSelected ? 1.0 : (isCached ? 0.56 : 0.72),
    fillColor: isSelected ? '#f3cf4a' : (isCached ? '#2f80c8' : '#050706'),
    fillOpacity: isSelected ? 0.2 : (isCached ? 0.0 : 0.46),
    dashArray: isCached ? null : '4 4'
  };
}

function kmSize(tile) {
  return (tile.size_m / 1000).toFixed(0) + 'km x ' + (tile.size_m / 1000).toFixed(0) + 'km';
}

function selectionId(sel) {
  var hemi = sel.northern ? 'n' : 's';
  return 'z' + sel.zone + hemi + '_e' + sel.easting + '_n' + sel.northing +
    '_w' + sel.width_m + '_h' + sel.height_m + '_s' + sel.size_m;
}

function setText(id, value) {
  var el = document.getElementById(id);
  if (el) el.textContent = value;
}

function formatKm(meters) {
  return (meters / 1000).toFixed(0) + ' km';
}

function selectionTileIds(sel) {
  return sel && sel.tiles ? sel.tiles.map(function(tile) { return tile.tile_id; }) : [];
}

function selectionPayloadFromSelection(sel) {
  if (!sel) return null;
  return {
    selection_id: sel.selection_id,
    tile_ids: selectionTileIds(sel),
    bbox: sel.bbox,
    saved_at: Date.now()
  };
}

function persistSelection() {
  var payload = selectionPayloadFromSelection(selection);
  if (!payload || !payload.tile_ids.length) return;
  try {
    if (window.sessionStorage) {
      window.sessionStorage.setItem(selectionStorageKey, JSON.stringify(payload));
    }
  } catch (e) {}
  fetch('/selection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tile_ids: payload.tile_ids }),
    keepalive: true
  }).catch(function() {});
}

function clearPersistedSelection() {
  pendingRestoreTileIds = null;
  pendingRestoreLogged = false;
  if (!window.sessionStorage) return;
  try {
    window.sessionStorage.removeItem(selectionStorageKey);
  } catch (e) {}
  fetch('/selection/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    keepalive: true
  }).catch(function() {});
}

function loadPersistedSelection() {
  if (!window.sessionStorage) return null;
  try {
    var raw = window.sessionStorage.getItem(selectionStorageKey);
    if (!raw) return null;
    var payload = JSON.parse(raw);
    if (!payload || !payload.tile_ids || !payload.tile_ids.length) return null;
    return payload;
  } catch (e) {
    return null;
  }
}

function restoreRememberedSelection() {
  var localPayload = loadPersistedSelection();
  if (restoreSelectionFromPayload(localPayload)) return;
  fetch('/selection')
  .then(function(r) { return r.json(); })
  .then(function(payload) {
    if (payload && payload.available) restoreSelectionFromPayload(payload);
  })
  .catch(function() {});
}

function restoreSelectionFromPayload(payload) {
  if (!payload || !payload.tile_ids || !payload.tile_ids.length) return false;
  if (payload.bbox && payload.bbox.length === 4) {
    map.fitBounds([[payload.bbox[1], payload.bbox[0]], [payload.bbox[3], payload.bbox[2]]], {
      padding: [60, 60],
      maxZoom: 16
    });
  }
  pendingRestoreTileIds = payload.tile_ids.slice();
  pendingRestoreLogged = false;
  if (lastGridData && lastGridData.tiles && lastGridData.tiles.length) {
    restorePendingSelection();
    return true;
  }
  scheduleGridLoad();
  return true;
}

function restorePendingSelection() {
  if (!pendingRestoreTileIds || !pendingRestoreTileIds.length || !lastGridData || !lastGridData.tiles) {
    return false;
  }
  var wanted = {};
  pendingRestoreTileIds.forEach(function(id) { wanted[id] = true; });
  var tiles = lastGridData.tiles.filter(function(tile) { return !!wanted[tile.tile_id]; });
  if (tiles.length !== pendingRestoreTileIds.length) {
    return false;
  }
  var previous = pendingRestoreTileIds;
  pendingRestoreTileIds = null;
  setSelection(tiles, { silent: true });
  if (!pendingRestoreLogged) {
    log('已恢复上次框选: ' + selection.selection_id + '  ' + previous.length + ' 格', 'ok');
    pendingRestoreLogged = true;
  }
  return true;
}

function updateTileDisplay() {
  var el = document.getElementById('tile-display');
  if (!selection) {
    el.textContent = '尚未框选网格';
    setText('area-id-chip', '未选择区域');
    setText('selection-bbox', '--');
    updateSelectionButtons(false);
    updateMapToolButtons();
    return;
  }
  var b = selection.bbox;
  var total = selection.tiles.length;
  var cached = selection.tiles.filter(function(tile) { return tile.cached; }).length;
  var cacheText = cached === total ? '全部已有本地缓存' : ('已缓存 ' + cached + '/' + total + '，其余运行时下载');
  var bboxText = 'W ' + b[0].toFixed(6) + ' / S ' + b[1].toFixed(6) +
    ' / E ' + b[2].toFixed(6) + ' / N ' + b[3].toFixed(6);
  el.textContent =
    selection.selection_id + '\n' +
    selection.cols + ' x ' + selection.rows + ' 格 · ' +
    formatKm(selection.width_m) + ' x ' + formatKm(selection.height_m) + ' · ' + cacheText + '\n' +
    bboxText;
  setText('area-id-chip', selection.selection_id);
  setText('selection-bbox', bboxText);
  updateSelectionButtons(false);
  updateMapToolButtons();
}

function syncDrawnSelectionLayer() {
  if (!drawnItems || !selection || !selection.bbox) return;
  drawnItems.clearLayers();
  var b = selection.bbox;
  L.rectangle([[b[1], b[0]], [b[3], b[2]]], {
    opacity: 0,
    fillOpacity: 0
  }).addTo(drawnItems);
}

function refreshTileStyles() {
  gridLayer.eachLayer(function(layer) {
    if (layer.vcTile) layer.setStyle(tileStyle(layer.vcTile));
  });
}

function bboxIntersects(bounds, bbox) {
  return !(bbox[2] < bounds.getWest() || bbox[0] > bounds.getEast() ||
           bbox[3] < bounds.getSouth() || bbox[1] > bounds.getNorth());
}

function setSelection(seedTiles, options) {
  options = options || {};
  if (!seedTiles || !seedTiles.length) {
    log('没有框到网格，请放大后重试。', 'err');
    return;
  }
  var zone = seedTiles[0].zone;
  var northern = seedTiles[0].northern;
  var size = seedTiles[0].size_m;
  var eastings = seedTiles.map(function(tile) { return tile.easting; });
  var northings = seedTiles.map(function(tile) { return tile.northing; });
  var minE = Math.min.apply(null, eastings);
  var maxE = Math.max.apply(null, eastings);
  var minN = Math.min.apply(null, northings);
  var maxN = Math.max.apply(null, northings);
  var rectTiles = (lastGridData.tiles || []).filter(function(tile) {
    return tile.zone === zone && tile.northern === northern && tile.size_m === size &&
      tile.easting >= minE && tile.easting <= maxE &&
      tile.northing >= minN && tile.northing <= maxN;
  });
  var cols = Math.round((maxE - minE) / size) + 1;
  var rows = Math.round((maxN - minN) / size) + 1;
  var expected = cols * rows;
  if (rectTiles.length !== expected) {
    clearSelection();
    log('[错误] 框选结果跨出了当前已加载网格，请稍微缩小框选或放大地图。', 'err');
    return;
  }
  if (expected > maxSelectionTiles) {
    clearSelection();
    log('[错误] 本次框选 ' + expected + ' 格，超过上限 ' + maxSelectionTiles + ' 格。', 'err');
    return;
  }
  rectTiles.sort(function(a, b) {
    if (a.northing !== b.northing) return a.northing - b.northing;
    return a.easting - b.easting;
  });
  var bbox = [
    Math.min.apply(null, rectTiles.map(function(tile) { return tile.bbox[0]; })),
    Math.min.apply(null, rectTiles.map(function(tile) { return tile.bbox[1]; })),
    Math.max.apply(null, rectTiles.map(function(tile) { return tile.bbox[2]; })),
    Math.max.apply(null, rectTiles.map(function(tile) { return tile.bbox[3]; }))
  ];
  selection = {
    zone: zone,
    northern: northern,
    easting: minE,
    northing: minN,
    cols: cols,
    rows: rows,
    size_m: size,
    width_m: cols * size,
    height_m: rows * size,
    bbox: bbox,
    tiles: rectTiles
  };
  selection.selection_id = selectionId(selection);
  selectedTileIds = {};
  rectTiles.forEach(function(tile) { selectedTileIds[tile.tile_id] = true; });
  updateTileDisplay();
  syncDrawnSelectionLayer();
  refreshTileStyles();
  persistSelection();
  setRunStatus('warn', '待命', 0, '已选择区域，等待执行');
  var cached = rectTiles.filter(function(tile) { return tile.cached; }).length;
  if (!options.silent) {
    log('已框选: ' + selection.selection_id + '  ' + rectTiles.length + ' 格，已缓存 ' + cached + '/' + rectTiles.length, 'ok');
  }
}

function selectTilesByBounds(bounds) {
  if (!lastGridData || !lastGridData.tiles || !lastGridData.tiles.length) {
    log('网格尚未加载完成，请稍等。', 'err');
    return;
  }
  var hits = lastGridData.tiles.filter(function(tile) {
    return bboxIntersects(bounds, tile.bbox);
  });
  setSelection(hits);
}

function selectTileByLatLng(latlng) {
  if (!lastGridData || !lastGridData.tiles || !lastGridData.tiles.length) {
    log('网格尚未加载完成，请稍等。', 'err');
    return;
  }
  var hit = null;
  for (var i = 0; i < lastGridData.tiles.length; i += 1) {
    var tile = lastGridData.tiles[i];
    var b = tile.bbox;
    if (latlng.lng >= b[0] && latlng.lng <= b[2] && latlng.lat >= b[1] && latlng.lat <= b[3]) {
      hit = tile;
      break;
    }
  }
  if (!hit) {
    log('未点中当前视口网格，请放大或等待网格加载。', 'err');
    return;
  }
  setSelection([hit]);
}

function clearSelection() {
  selection = null;
  selectedTileIds = {};
  drawnItems.clearLayers();
  clearPersistedSelection();
  updateTileDisplay();
  refreshTileStyles();
  setRunStatus('warn', '待命', 0, '等待选择区域');
}

function renderGrid(data) {
  gridLayer.clearLayers();
  if (!data) return;
  lastGridData = data;
  if (data.truncated) {
    document.getElementById('grid-status').textContent = data.message || '视口太大，请放大';
    return;
  }
  var shown = 0;
  var cached = 0;
  data.tiles.forEach(function(tile) {
    if (tile.cached) cached += 1;
    var options = tileStyle(tile);
    options.interactive = false;
    var poly = L.polygon(tile.corners, options);
    poly.vcTile = tile;
    poly.addTo(gridLayer);
    shown += 1;
  });
  document.getElementById('grid-status').textContent =
    '显示 ' + shown + ' / ' + data.tiles.length + ' 格；已缓存 ' + cached + ' 格';
  restorePendingSelection();
  refreshTileStyles();
}

function loadGrid() {
  map.invalidateSize();
  var size = map.getSize();
  if (!size || size.x <= 0 || size.y <= 0) {
    document.getElementById('grid-status').textContent = '等待地图布局...';
    scheduleGridLoad();
    return;
  }
  var b = map.getBounds();
  if (!(b.getWest() < b.getEast() && b.getSouth() < b.getNorth())) {
    document.getElementById('grid-status').textContent = '等待地图视口稳定...';
    scheduleGridLoad();
    return;
  }
  var req = ++gridRequestId;
  var url = '/tiles?west=' + encodeURIComponent(b.getWest()) +
    '&south=' + encodeURIComponent(b.getSouth()) +
    '&east=' + encodeURIComponent(b.getEast()) +
    '&north=' + encodeURIComponent(b.getNorth());
  document.getElementById('grid-status').textContent = '加载网格中...';
  fetch(url)
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (req !== gridRequestId) return;
    renderGrid(data);
  })
  .catch(function(e) {
    document.getElementById('grid-status').textContent = '网格加载失败';
    log('[错误] 网格加载失败: ' + e, 'err');
  });
}

function scheduleGridLoad() {
  clearTimeout(gridTimer);
  gridTimer = setTimeout(loadGrid, 120);
}

map.on('moveend zoomend', scheduleGridLoad);
window.addEventListener('resize', function() {
  map.invalidateSize();
  scheduleGridLoad();
});
restoreRememberedSelection();
scheduleGridLoad();

function categorizeLine(line) {
  var l = line.toLowerCase();
  
  // Model QA check
  if (l.indexOf('[modelqa]') >= 0 || l.indexOf('model qa') >= 0 || l.indexOf('report: reports/') >= 0 || l.indexOf('checks={') >= 0) {
    return 'qa';
  }
  // Model QA specific indicator lines
  if (l.indexOf('[ok]') >= 0 && (
      l.indexOf('required_nodes') >= 0 || 
      l.indexOf('terrain_density') >= 0 || 
      l.indexOf('building_color') >= 0 || 
      l.indexOf('footprint_bevel') >= 0 || 
      l.indexOf('building_normals') >= 0 || 
      l.indexOf('foundation_tags') >= 0 || 
      l.indexOf('foundation_normals') >= 0 || 
      l.indexOf('foundation_alignment') >= 0 || 
      l.indexOf('building_terrain_fit') >= 0 || 
      l.indexOf('road_terrain_fit') >= 0
  )) {
    return 'qa';
  }
  if (l.indexOf('[warn] road_faces') >= 0 || l.indexOf('[warn] road_clipped_faces') >= 0) {
    return 'qa';
  }
  
  // Houdini Cooking & SOP pipeline
  if (l.indexOf('[houdini') >= 0 || 
      l.indexOf('cooking:') >= 0 || 
      l.indexOf('osm_import') >= 0 || 
      l.indexOf('dem_terrain') >= 0 || 
      l.indexOf('dem_subdivide') >= 0 ||
      l.indexOf('bld_footprint_bevel') >= 0 || 
      l.indexOf('extract_buildings') >= 0 || 
      l.indexOf('snap_bld_to_terrain') >= 0 || 
      l.indexOf('extrude_buildings') >= 0 || 
      l.indexOf('post_normals') >= 0 || 
      l.indexOf('road_strips') >= 0 || 
      l.indexOf('bld_clipped') >= 0 || 
      l.indexOf('road_clipped') >= 0 || 
      l.indexOf('bld_foundation') >= 0 || 
      l.indexOf('bld_with_foundation') >= 0 || 
      l.indexOf('road_extrude') >= 0 || 
      l.indexOf('viewport') >= 0 || 
      l.indexOf('save hip') >= 0) {
    return 'houdini';
  }
  
  // Refinement / Offline Cleaning
  if (l.indexOf('[数据精炼]') >= 0 || 
      l.indexOf('[dtm]') >= 0 || 
      l.indexOf('[tile cache]') >= 0 || 
      l.indexOf('download') >= 0 || 
      l.indexOf('[probe]') >= 0 || 
      l.indexOf('earth engine') >= 0 || 
      l.indexOf('fabdem') >= 0 || 
      l.indexOf('geotiff') >= 0 || 
      l.indexOf('csv') >= 0 || 
      l.indexOf('osm') >= 0) {
    return 'clean';
  }
  
  return null;
}

function writeToPanel(panelId, msg, cls) {
  var el = document.getElementById('log-panel-' + panelId);
  if (!el) return;
  
  if (el.textContent.indexOf('等待') === 0) {
    el.textContent = '';
  }
  
  var line = document.createElement('span');
  if (cls) line.className = cls;
  line.textContent = msg + '\n';
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function log(msg, cls) {
  writeToPanel('all', msg, cls);
  
  var category = categorizeLine(msg);
  if (category) {
    writeToPanel(category, msg, cls);
  }
}

function switchTab(panelId) {
  var btns = document.querySelectorAll('.tab-btn');
  btns.forEach(function(btn) {
    btn.classList.remove('active');
  });
  
  var activeBtn = document.querySelector('button[onclick="switchTab(\'' + panelId + '\')"]');
  if (activeBtn) {
    activeBtn.classList.add('active');
  }
  
  var panels = document.querySelectorAll('.log-panel');
  panels.forEach(function(p) {
    if (p.id === 'log-panel-' + panelId) {
      p.style.display = 'block';
      p.scrollTop = p.scrollHeight;
    } else {
      p.style.display = 'none';
    }
  });
}

var _pollTimer = null;
var _lastLogLen = 0;
var _lastExportLogLen = 0;
var _lastFailureKey = '';
var _houdiniOpenPollTimer = null;

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
  .then(d => {
    var pct = d.pct || 0;
    document.getElementById('progress-bar').style.width = pct + '%';
    document.getElementById('progress-text').textContent = pct + '%';
    document.getElementById('step-label').textContent = d.step_label || '运行中...';
    updateRunStatusFromHealth(d);
    updateSoftwarePath(d.software_paths);

    if (d.log_lines && d.log_lines.length > _lastLogLen) {
      var newLines = d.log_lines.slice(_lastLogLen);
      for (var i = 0; i < newLines.length; i++) {
        var line = newLines[i];
        var cls = 'dim';
        if (line.indexOf('[OK]') >= 0) cls = 'ok';
        else if (line.indexOf('[ERR]') >= 0 || line.indexOf('[FAIL]') >= 0) cls = 'err';
        else if (line.match(/^\[\d+\/\d+\]/)) cls = 'step';
        log(line, cls);
      }
      _lastLogLen = d.log_lines.length;
    }

    if (d.export_log_lines && d.export_log_lines.length > _lastExportLogLen) {
      var exportLines = d.export_log_lines.slice(_lastExportLogLen);
      for (var j = 0; j < exportLines.length; j++) {
        var exLine = exportLines[j];
        var exCls = 'dim';
        if (exLine.indexOf('[OK]') >= 0 || exLine.indexOf(' OK:') >= 0) exCls = 'ok';
        else if (exLine.indexOf('[ERR]') >= 0 || exLine.indexOf('[FAIL]') >= 0 || exLine.indexOf('[WARN]') >= 0) exCls = 'err';
        log(exLine, exCls);
      }
      _lastExportLogLen = d.export_log_lines.length;
    }
    updateExportButton(!!d.export_available, !!d.export_running || !!d.running);
    setHoudiniBadge(!!d.houdini_available, d.houdini_asset);
    updateSelectionButtons(!!d.running);
    updateDownloadedAreaCount(d);

    if (d.export_done && !d.export_running) {
      clearInterval(_pollTimer);
      _pollTimer = null;
      refreshServiceState();
      return;
    }

    if (d.done && !d.export_running) {
      clearInterval(_pollTimer);
      _pollTimer = null;
      document.getElementById('progress-bar').style.width = '100%';
      document.getElementById('progress-text').textContent = '100%';
      if (d.ok) {
        document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #2e7d32, #a5d6a7)';
        var doneLabel = d.operation === 'download' ? '[OK] 数据下载完成' : '[OK] 生成完成';
        var doneLog = d.operation === 'download' ? '[OK] 数据下载完成！区域: ' : '[OK] 生成完成！区域: ';
        document.getElementById('step-label').textContent = doneLabel;
        setRunStatus('ok', '完成', 100, doneLabel);
        log(doneLog + d.name, 'ok');
        if (d.run_id) log('run_id: ' + d.run_id, 'dim');
        if (d.auto_shutdown_on_success) {
          log('3 秒后自动关闭页面，5 秒后停止本地服务...', 'dim');
          setTimeout(function() {
            window.open('', '_self');
            window.close();
            document.body.innerHTML = '<div style="font-family:Segoe UI,Arial,sans-serif;background:#0f1110;color:#b9efa9;height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column;"><h2>[OK] VirtualCity 生成完成</h2><p>本地服务已自动停止，可以关闭此页面。</p></div>';
          }, 3000);
        } else {
          log('状态服务保持运行，可继续查看 /status 或继续选择网格测试。', 'dim');
          updateSelectionButtons(false);
          scheduleGridLoad();
          refreshServiceState();
        }
      } else {
        document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #c62828, #ef9a9a)';
        var failDetail = failureStatusDetail(d.failure_summary, '[FAIL] 管线出错');
        document.getElementById('step-label').textContent = failDetail;
        setRunStatus('off', '失败', d.pct || 0, failDetail);
        setFailureSummary(d.failure_summary);
        logFailureSummary(d.failure_summary, d.returncode);
        updateSelectionButtons(false);
        refreshServiceState();
      }
    }
  })
  .catch(function() { /* server may be restarting */ });
}

function submitSelectedArea(endpoint, actionLabel) {
  if (!selection) return;
  var name = selection.selection_id;
  var b = selection.bbox;
  updateSelectionButtons(true);
  document.getElementById('log-panel-all').innerHTML = '';
  document.getElementById('log-panel-clean').innerHTML = '等待数据下载或精炼...';
  document.getElementById('log-panel-houdini').innerHTML = '等待 Houdini RPYC 执行...';
  document.getElementById('log-panel-qa').innerHTML = '等待 Model QA 诊断报告...';
  _lastLogLen = 0;
  _lastExportLogLen = 0;
  _lastFailureKey = '';
  setFailureSummary(null);
  document.getElementById('progress-container').style.display = 'block';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-bar').style.background = 'linear-gradient(90deg, #137e75, #21b6a8)';
  document.getElementById('progress-text').textContent = '0%';
  document.getElementById('step-label').textContent = '准备中...';
  setRunStatus('warn', '启动中', 0, actionLabel + ': ' + name);
  log('[' + new Date().toLocaleTimeString() + '] ' + actionLabel + ': ' + name, 'ok');
  log('bbox = [' + b[0]+', '+b[1]+', '+b[2]+', '+b[3]+']', 'dim');
  updateExportButton(false, true);

  fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      tile_ids: selection.tiles.map(function(tile) { return tile.tile_id; })
    })
  })
  .then(r => r.json())
  .then(d => {
    if (d.ok) {
      log(d.message || '任务已启动...', 'dim');
      _pollTimer = setInterval(pollStatus, 1000);
    } else {
      log('[错误] ' + d.message, 'err');
      updateSelectionButtons(false);
      refreshServiceState();
    }
  })
  .catch(e => {
    log('[网络错误] ' + e, 'err');
    updateSelectionButtons(false);
    refreshServiceState();
  });
}

function runPipeline() {
  submitSelectedArea('/run', '提交 Houdini 生成');
}

function downloadData() {
  submitSelectedArea('/download-data', '提交数据下载');
}

function ensurePolling() {
  if (!_pollTimer) _pollTimer = setInterval(pollStatus, 1000);
}

function exportFbx() {
  document.getElementById('export-btn').disabled = true;
  _lastExportLogLen = 0;
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

refreshServiceState();
refreshDataSources();
startPageSession();
</script>
</body>
</html>"""
