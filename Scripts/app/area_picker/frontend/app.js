var selection = null;
var selectedTileIds = {};
var lastGridData = null;
var gridRequestId = 0;
var gridTimer = null;
var maxSelectionTiles = window.VC_CONFIG.maxSelectionTiles;
var shutdownWithPage = window.VC_CONFIG.shutdownWithPage;
var pageSessionTimer = null;
var selectionStorageKey = 'vc.areaPicker.selection.v1';
var frontendRefreshWorkspaceKey = 'vc.areaPicker.refreshWorkspace.v1';
var dccPathCachePrefix = 'virtualcity.dcc.path.';
var pendingRestoreTileIds = null;
var pendingRestoreLogged = false;
var pointSelectActive = false;
var gridVisible = false;
var selectionToolButtons = {};
var mapReady = false;
var rectToolArmed = false;
var rectDragging = false;
var rectStart = null;
var activeWorkspaceId = 'news';
var cityPreviewActive = false;
var lastCityView = null;
var actionPanelCollapsed = false;
var houdiniSideResizeState = null;
var WORKSPACE_KINDS = {
  news: 'earth',
  'city-preview': 'earth',
  neighborhood: 'earth',
  game: 'game',
  houdini: 'houdini'
};

var VECTOR_STYLE_URL = '/area-picker/basemap-style.json?v=' + window.VC_CONFIG.version;
var OSM_RASTER_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: [
        'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png'
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© OpenStreetMap contributors'
    }
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
};
var SATELLITE_GLOBE_STYLE = {
  version: 8,
  projection: { type: 'globe' },
  terrain: { source: 'terrain-dem', exaggeration: 20 },
  sources: {
    satellite: {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
      ],
      tileSize: 256,
      maxzoom: 19,
      attribution: 'Imagery © Esri, Maxar, Earthstar Geographics'
    },
    'terrain-dem': {
      type: 'raster-dem',
      tiles: [
        'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
      ],
      tileSize: 256,
      maxzoom: 15,
      encoding: 'terrarium',
      attribution: 'Elevation © Mapzen'
    }
  },
  layers: [
    { id: 'satellite', type: 'raster', source: 'satellite' }
  ]
};
var BASEMAP_STYLES = [
  { id: 'positron', label: '默认', style: 'https://tiles.openfreemap.org/styles/positron', extrusionColor: 'hsl(40,7%,80%)', buildingRGB: [223, 220, 214] },
  { id: 'satellite', label: '卫星', style: SATELLITE_GLOBE_STYLE }
];
var currentBasemap = 'positron';

function getBasemapStyle(id) {
  for (var i = 0; i < BASEMAP_STYLES.length; i++) {
    if (BASEMAP_STYLES[i].id === id) return BASEMAP_STYLES[i];
  }
  return BASEMAP_STYLES[0];
}

var map = new maplibregl.Map({
  container: 'map',
  style: getBasemapStyle(currentBasemap).style,
  center: [window.VC_CONFIG.lon, 20],
  zoom: 2.5,
  maxPitch: 65,
  attributionControl: false,
  dragRotate: false,
  pitchWithRotate: false,
  dragPan: {
    linearity: 0.25,
    easing: function(t) { return 1 - Math.pow(1 - t, 3); },
    maxSpeed: 2000,
    deceleration: 2200
  }
});
map.touchZoomRotate.disableRotation();
if (map.scrollZoom) map.scrollZoom.disable();
var cameraController = createCameraController(map);
cameraController.bindInput();

function createCameraController(mapInstance) {
  var MODES = {
    IDLE_2D: '2d-idle',
    AUTO_SPIN: '2d-auto-spin',
    WHEEL_ZOOM: 'wheel-zoom',
    MANUAL_3D: '3d-manual',
    CITY_FLYING: '3d-city-flying',
    CITY_ORBIT: '3d-city-orbit',
    PROGRAMMATIC_FIT: 'programmatic-fit'
  };

  var CITY_PITCH = 55;
  var AUTO_SPIN_MAX_ZOOM = 4.5;
  var AUTO_SPIN_DEGREES_PER_SEC = 1;
  var CITY_ORBIT_DEGREES_PER_SEC = 6;
  var SPIN_RAMP_MS = 1400;
  var ORBIT_RAMP_MS = 1200;
  var WHEEL_HOLD_MS = 500;
  var WHEEL_BOUNDARY_HOLD_MS = 12000;
  var MANUAL_HOLD_MS = 500;
  var PROGRAMMATIC_HOLD_MS = 1500;
  var ZOOM_EDGE_EPS = 0.02;
  var ZOOM_NOOP_EPS = 0.0001;
  var MAX_FRAME_DT = 0.05;
  var ANCHOR_ROUNDTRIP_TOLERANCE_PX = 8;
  var MAX_ANCHOR_CORRECTION_PX = 160;
  var GLOBE_EDGE_TOLERANCE_PX = 24;

  var WHEEL_FRICTION = 0.86;
  var WHEEL_IMPULSE = 0.0011;
  var WHEEL_MAX_VELOCITY = 0.22;
  var WHEEL_MIN_VELOCITY = 0.0009;

  var ROTATE_SPEED = 0.35;
  var PITCH_SPEED = 0.25;

  var mode = MODES.IDLE_2D;
  var rafId = null;
  var resumeTimer = null;
  var userHoldUntil = 0;
  var lastFrameTime = 0;
  var spinRampStart = 0;
  var orbitRampStart = 0;
  var zoomVelocity = 0;
  var anchorPoint = null;
  var wheelAnchorMode = null;
  var moveToken = 0;
  var inputBound = false;
  var viewToggleBound = false;
  var middleDragging = false;
  var lastMouseX = 0;
  var lastMouseY = 0;

  function easeRamp(t) {
    t = Math.max(0, Math.min(1, t));
    return t * t * (3 - 2 * t);
  }

  function isFlatView() {
    return mapInstance.getPitch() <= 0.5;
  }

  function isEasing() {
    return !!(mapInstance.isEasing && mapInstance.isEasing());
  }

  function setMode(next) {
    if (mode === next) return;
    mode = next;
    lastFrameTime = 0;
    if (next !== MODES.AUTO_SPIN) spinRampStart = 0;
    if (next !== MODES.CITY_ORBIT) orbitRampStart = 0;
  }

  function requestFrame() {
    if (!rafId) rafId = requestAnimationFrame(frame);
  }

  function clearResumeTimer() {
    if (resumeTimer) {
      clearTimeout(resumeTimer);
      resumeTimer = null;
    }
  }

  function stopMapEase() {
    if (isEasing() && mapInstance.stop) mapInstance.stop();
  }

  function resetWheelZoom() {
    zoomVelocity = 0;
    anchorPoint = null;
    wheelAnchorMode = null;
  }

  function finishWheelZoom() {
    resetWheelZoom();
    setMode(isFlatView() ? MODES.IDLE_2D : MODES.MANUAL_3D);
    scheduleAutoResume();
  }

  function interruptForWheel() {
    moveToken++;
    if (mode === MODES.AUTO_SPIN) setMode(MODES.IDLE_2D);
    if (mode === MODES.CITY_ORBIT || mode === MODES.CITY_FLYING || mode === MODES.PROGRAMMATIC_FIT) {
      setMode(isFlatView() ? MODES.IDLE_2D : MODES.MANUAL_3D);
    }
  }

  function stopAutoBehaviorsForManual() {
    moveToken++;
    if (mode === MODES.CITY_ORBIT) setMode(MODES.MANUAL_3D);
    if (mode === MODES.AUTO_SPIN) setMode(MODES.IDLE_2D);
    if (mode === MODES.WHEEL_ZOOM) finishWheelZoom();
  }

  function holdAutoSpin(ms) {
    userHoldUntil = Math.max(userHoldUntil, performance.now() + ms);
    if (mode === MODES.AUTO_SPIN) setMode(MODES.IDLE_2D);
    clearResumeTimer();
    scheduleAutoResume();
  }

  function canAutoSpin(now) {
    return mode === MODES.IDLE_2D &&
      isFlatView() &&
      mapInstance.getZoom() <= AUTO_SPIN_MAX_ZOOM &&
      !isEasing() &&
      now >= userHoldUntil;
  }

  function scheduleAutoResume() {
    clearResumeTimer();
    if (mode !== MODES.IDLE_2D) return;
    if (!isFlatView() || mapInstance.getZoom() > AUTO_SPIN_MAX_ZOOM || isEasing()) return;

    var now = performance.now();
    var delay = Math.max(0, userHoldUntil - now);
    resumeTimer = setTimeout(maybeStartAutoSpin, delay);
  }

  function maybeStartAutoSpin() {
    clearResumeTimer();
    if (!canAutoSpin(performance.now())) {
      scheduleAutoResume();
      return;
    }
    setMode(MODES.AUTO_SPIN);
    lastFrameTime = 0;
    spinRampStart = 0;
    requestFrame();
  }

  function stepAutoSpin(now) {
    if (!isFlatView() || mapInstance.getZoom() > AUTO_SPIN_MAX_ZOOM) {
      setMode(MODES.IDLE_2D);
      scheduleAutoResume();
      return false;
    }
    if (isEasing()) {
      lastFrameTime = 0;
      spinRampStart = 0;
      return true;
    }
    if (!spinRampStart) spinRampStart = now;
    if (lastFrameTime) {
      var dt = Math.min((now - lastFrameTime) / 1000, MAX_FRAME_DT);
      var speed = AUTO_SPIN_DEGREES_PER_SEC * easeRamp((now - spinRampStart) / SPIN_RAMP_MS);
      var center = mapInstance.getCenter();
      center.lng = ((center.lng + speed * dt + 180) % 360) - 180;
      mapInstance.setCenter(center);
    }
    lastFrameTime = now;
    return true;
  }

  function normalizeWheelDelta(e) {
    var delta = e.deltaY;
    if (e.deltaMode === 1) delta *= 20;
    else if (e.deltaMode === 2) delta *= 400;
    return delta;
  }

  function isWheelAtZoomBoundary(delta) {
    var current = mapInstance.getZoom();
    var zoomingOut = delta > 0;
    var zoomingIn = delta < 0;
    return (zoomingOut && current <= mapInstance.getMinZoom() + ZOOM_EDGE_EPS) ||
      (zoomingIn && current >= mapInstance.getMaxZoom() - ZOOM_EDGE_EPS);
  }

  function pointIsFinite(point) {
    return point && Number.isFinite(point.x) && Number.isFinite(point.y);
  }

  function distanceBetweenPoints(a, b) {
    var dx = a.x - b.x;
    var dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function wrapLng(lng) {
    return ((lng + 540) % 360) - 180;
  }

  function projectedPoint(lngLat) {
    try {
      var point = mapInstance.project(lngLat);
      return pointIsFinite(point) ? point : null;
    } catch (e) {
      return null;
    }
  }

  function visibleGlobeRadiusPx(centerPoint) {
    var center = mapInstance.getCenter();
    var candidates = [
      projectedPoint([wrapLng(center.lng + 90), center.lat]),
      projectedPoint([wrapLng(center.lng - 90), center.lat])
    ];
    var distances = [];
    candidates.forEach(function(candidate) {
      if (!candidate) return;
      var distance = distanceBetweenPoints(candidate, centerPoint);
      if (Number.isFinite(distance) && distance > 0) distances.push(distance);
    });
    if (!distances.length) return Infinity;
    distances.sort(function(a, b) { return a - b; });
    return distances[0];
  }

  function pointInsideVisibleGlobe(point) {
    if (!pointIsFinite(point)) return false;
    var centerPoint = projectedPoint(mapInstance.getCenter());
    if (!centerPoint) return true;
    var radius = visibleGlobeRadiusPx(centerPoint);
    if (!Number.isFinite(radius)) return true;
    var canvas = mapInstance.getCanvas();
    var canvasDiagonal = Math.sqrt(canvas.clientWidth * canvas.clientWidth + canvas.clientHeight * canvas.clientHeight);
    if (radius > canvasDiagonal * 1.4) return true;
    return distanceBetweenPoints(point, centerPoint) <= radius + GLOBE_EDGE_TOLERANCE_PX;
  }

  function resolveWheelAnchor(point) {
    if (!wheelAnchorMode) {
      wheelAnchorMode = pointInsideVisibleGlobe(point) ? 'cursor' : 'center';
    }
    if (wheelAnchorMode === 'cursor') {
      anchorPoint = point;
    } else {
      anchorPoint = null;
    }
  }
  function anchorPointOnGlobe(point) {
    if (!pointInsideVisibleGlobe(point)) return false;
    var lngLat = mapInstance.unproject(point);
    if (!lngLat || !Number.isFinite(lngLat.lng) || !Number.isFinite(lngLat.lat)) return false;
    var roundTrip = mapInstance.project(lngLat);
    return pointIsFinite(roundTrip) && distanceBetweenPoints(roundTrip, point) <= ANCHOR_ROUNDTRIP_TOLERANCE_PX;
  }

  function applyZoomAround(z) {
    var clamped = Math.max(mapInstance.getMinZoom(), Math.min(mapInstance.getMaxZoom(), z));
    if (Math.abs(clamped - mapInstance.getZoom()) < ZOOM_NOOP_EPS) return;
    if (!anchorPoint || !anchorPointOnGlobe(anchorPoint)) {
      mapInstance.setZoom(clamped);
      return;
    }

    var beforeLngLat = mapInstance.unproject(anchorPoint);
    mapInstance.setZoom(clamped);

    var afterPoint = mapInstance.project(beforeLngLat);
    if (!pointIsFinite(afterPoint)) return;

    var dx = afterPoint.x - anchorPoint.x;
    var dy = afterPoint.y - anchorPoint.y;
    var correction = Math.sqrt(dx * dx + dy * dy);
    if (!Number.isFinite(correction) || correction > MAX_ANCHOR_CORRECTION_PX) return;

    if (dx || dy) {
      var center = mapInstance.project(mapInstance.getCenter());
      var nextCenter = new maplibregl.Point(center.x + dx, center.y + dy);
      mapInstance.setCenter(mapInstance.unproject(nextCenter));
    }
  }

  function stepWheelZoom() {
    if (Math.abs(zoomVelocity) < WHEEL_MIN_VELOCITY) {
      finishWheelZoom();
      return false;
    }
    var current = mapInstance.getZoom();
    var next = current + zoomVelocity;
    var min = mapInstance.getMinZoom();
    var max = mapInstance.getMaxZoom();
    if (next <= min || next >= max) {
      applyZoomAround(next <= min ? min : max);
      finishWheelZoom();
      return false;
    }
    applyZoomAround(next);
    zoomVelocity *= WHEEL_FRICTION;
    return true;
  }

  function onWheel(e) {
    e.preventDefault();
    var delta = normalizeWheelDelta(e);
    if (!delta) return;

    holdAutoSpin(WHEEL_HOLD_MS);
    interruptForWheel();
    stopMapEase();

    if (isWheelAtZoomBoundary(delta)) {
      resetWheelZoom();
      setMode(isFlatView() ? MODES.IDLE_2D : MODES.MANUAL_3D);
      holdAutoSpin(WHEEL_BOUNDARY_HOLD_MS);
      return;
    }

    var rect = mapInstance.getCanvas().getBoundingClientRect();
    var wheelPoint = new maplibregl.Point(e.clientX - rect.left, e.clientY - rect.top);
    resolveWheelAnchor(wheelPoint);
    zoomVelocity += -delta * WHEEL_IMPULSE;
    zoomVelocity = Math.max(-WHEEL_MAX_VELOCITY, Math.min(WHEEL_MAX_VELOCITY, zoomVelocity));
    setMode(MODES.WHEEL_ZOOM);
    requestFrame();
  }

  function stepCityOrbit(now) {
    if (isEasing()) {
      lastFrameTime = 0;
      orbitRampStart = 0;
      return true;
    }
    if (!orbitRampStart) orbitRampStart = now;
    if (lastFrameTime) {
      var dt = Math.min((now - lastFrameTime) / 1000, MAX_FRAME_DT);
      var speed = CITY_ORBIT_DEGREES_PER_SEC * easeRamp((now - orbitRampStart) / ORBIT_RAMP_MS);
      mapInstance.setBearing(mapInstance.getBearing() + speed * dt);
    }
    lastFrameTime = now;
    return true;
  }

  function startCityOrbit() {
    setMode(MODES.CITY_ORBIT);
    lastFrameTime = 0;
    orbitRampStart = 0;
    requestFrame();
  }

  function frame(now) {
    rafId = null;
    var keepRunning = false;
    if (mode === MODES.AUTO_SPIN) keepRunning = stepAutoSpin(now);
    else if (mode === MODES.WHEEL_ZOOM) keepRunning = stepWheelZoom(now);
    else if (mode === MODES.CITY_ORBIT) keepRunning = stepCityOrbit(now);
    if (keepRunning) requestFrame();
  }

  function onManualInputStart() {
    holdAutoSpin(MANUAL_HOLD_MS);
    stopMapEase();
    stopAutoBehaviorsForManual();
  }

  function onMapZoomStart() {
    if (mode === MODES.WHEEL_ZOOM || mode === MODES.CITY_FLYING || mode === MODES.PROGRAMMATIC_FIT) return;
    onManualInputStart();
  }

  function onMouseDown(e) {
    onManualInputStart();
    if (e.button !== 1 || isFlatView()) return;
    e.preventDefault();
    stopMapEase();
    resetWheelZoom();
    setMode(MODES.MANUAL_3D);
    middleDragging = true;
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
  }

  function onMouseMove(e) {
    if (!middleDragging) return;
    var dx = e.clientX - lastMouseX;
    var dy = e.clientY - lastMouseY;
    lastMouseX = e.clientX;
    lastMouseY = e.clientY;
    mapInstance.setBearing(mapInstance.getBearing() + dx * ROTATE_SPEED);
    var nextPitch = mapInstance.getPitch() - dy * PITCH_SPEED;
    nextPitch = Math.max(0, Math.min(mapInstance.getMaxPitch(), nextPitch));
    mapInstance.setPitch(nextPitch);
  }

  function onMouseUp(e) {
    if (e.button !== 1 || !middleDragging) return;
    middleDragging = false;
    setMode(isFlatView() ? MODES.IDLE_2D : MODES.MANUAL_3D);
    syncViewToggle();
    scheduleAutoResume();
  }

  function bindInput() {
    if (inputBound) return;
    inputBound = true;
    var canvas = mapInstance.getCanvas();
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('touchstart', onManualInputStart, { passive: true });
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    mapInstance.on('dragstart', onManualInputStart);
    mapInstance.on('zoomstart', onMapZoomStart);
    mapInstance.on('pitchend', function() {
      syncViewToggle();
      if (isFlatView() && mode === MODES.MANUAL_3D) {
        setMode(MODES.IDLE_2D);
        scheduleAutoResume();
      }
    });
    mapInstance.on('moveend', scheduleAutoResume);
    mapInstance.on('zoomend', scheduleAutoResume);
  }

  function start() {
    setMode(isFlatView() ? MODES.IDLE_2D : MODES.MANUAL_3D);
    scheduleAutoResume();
  }

  function fitBounds2D(bbox, maxZoom) {
    if (!bbox || bbox.length !== 4) return;
    moveToken++;
    var token = moveToken;
    holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    resetWheelZoom();
    setMode(MODES.PROGRAMMATIC_FIT);
    mapInstance.once('moveend', function() {
      if (token !== moveToken) return;
      setMode(MODES.IDLE_2D);
      syncViewToggle();
      holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    });
    mapInstance.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], {
      padding: 60,
      maxZoom: maxZoom || 14,
      pitch: 0,
      bearing: 0,
      linear: false,
      curve: 1.42,
      speed: 2.4,
      easing: function(t) { return 1 - Math.pow(1 - t, 3); }
    });
  }

  function flyToCity(lng, lat, zoom) {
    if (typeof lng !== 'number' || typeof lat !== 'number') return;
    moveToken++;
    var token = moveToken;
    var targetZoom = zoom || 15;
    holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    resetWheelZoom();
    setMode(MODES.CITY_FLYING);
    var startBearing = mapInstance.getBearing();
    mapInstance.once('moveend', function() {
      if (token !== moveToken) return;
      startCityOrbit();
      syncViewToggle();
    });
    mapInstance.flyTo({
      center: [lng, lat],
      zoom: targetZoom,
      pitch: CITY_PITCH,
      bearing: startBearing - 25,
      speed: 2.4,
      curve: 1.2,
      essential: true
    });
  }

  function flyToWorld() {
    moveToken++;
    var token = moveToken;
    holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    resetWheelZoom();
    setMode(MODES.PROGRAMMATIC_FIT);
    mapInstance.once('moveend', function() {
      if (token !== moveToken) return;
      setMode(MODES.IDLE_2D);
      syncViewToggle();
      holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    });
    mapInstance.flyTo({
      center: [window.VC_CONFIG.lon, 20],
      zoom: 2.5,
      pitch: 0,
      bearing: 0,
      speed: 2.4,
      curve: 1.2,
      essential: true
    });
  }

  function enter3DInPlace() {
    moveToken++;
    var token = moveToken;
    holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    resetWheelZoom();
    setMode(MODES.CITY_FLYING);
    var startBearing = mapInstance.getBearing();
    mapInstance.easeTo({
      pitch: CITY_PITCH,
      bearing: startBearing - 25,
      duration: 800,
      easing: function(t) { return t * t * (3 - 2 * t); }
    });
    mapInstance.once('moveend', function() {
      if (token !== moveToken) return;
      startCityOrbit();
      syncViewToggle();
    });
  }

  function exitTo2D() {
    moveToken++;
    var token = moveToken;
    holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    resetWheelZoom();
    setMode(MODES.PROGRAMMATIC_FIT);
    mapInstance.easeTo({
      pitch: 0,
      bearing: 0,
      duration: 800,
      easing: function(t) { return t * t * (3 - 2 * t); }
    });
    mapInstance.once('moveend', function() {
      if (token !== moveToken) return;
      setMode(MODES.IDLE_2D);
      syncViewToggle();
      holdAutoSpin(PROGRAMMATIC_HOLD_MS);
    });
  }

  function setupViewToggle() {
    if (viewToggleBound) return;
    var to2d = document.querySelector('#view-toggle .view-toggle-2d');
    var to3d = document.querySelector('#view-toggle .view-toggle-3d');
    if (!to2d || !to3d) return;
    viewToggleBound = true;

    to3d.addEventListener('click', function() {
      if (!isFlatView()) {
        startCityOrbit();
        syncViewToggle();
      } else {
        enter3DInPlace();
      }
    });

    to2d.addEventListener('click', exitTo2D);
    syncViewToggle();
  }

  function syncViewToggle() {
    var to2d = document.querySelector('#view-toggle .view-toggle-2d');
    var to3d = document.querySelector('#view-toggle .view-toggle-3d');
    if (!to2d || !to3d) return;
    var is3d = !isFlatView();
    to3d.classList.toggle('active', is3d);
    to3d.setAttribute('aria-pressed', is3d ? 'true' : 'false');
    to2d.classList.toggle('active', !is3d);
    to2d.setAttribute('aria-pressed', !is3d ? 'true' : 'false');
  }

  return {
    bindInput: bindInput,
    start: start,
    setupViewToggle: setupViewToggle,
    syncViewToggle: syncViewToggle,
    fitBounds2D: fitBounds2D,
    flyToCity: flyToCity,
    flyToWorld: flyToWorld,
    enter3DInPlace: enter3DInPlace,
    exitTo2D: exitTo2D,
    isCityOrbitActive: function() { return mode === MODES.CITY_ORBIT; }
  };
}
function emptyFeatureCollection() {
  return { type: 'FeatureCollection', features: [] };
}

var deckOverlay = null;
var deckBuildingData = [];
var deckGroundData = [];
var deckRefreshTimer = null;
var sunLight = null;
var lightingEffect = null;

var VERTICAL_GRADIENT_BOTTOM = 0.78;
var BUILDING_AO_HEIGHT = 4.0;
var BUILDING_AO_STRENGTH = 0.85;

function BuildingShadingExtension() {}
BuildingShadingExtension.prototype = Object.create(deck.LayerExtension.prototype);
BuildingShadingExtension.prototype.constructor = BuildingShadingExtension;
BuildingShadingExtension.prototype.getShaders = function() {
  var bottom = VERTICAL_GRADIENT_BOTTOM.toFixed(4);
  var aoHeight = BUILDING_AO_HEIGHT.toFixed(4);
  var aoBottom = BUILDING_AO_STRENGTH.toFixed(4);
  return {
    inject: {
      'vs:#decl': '\nout float vGradientFrac;\nout float vBaseMeters;\n',
      'vs:#main-end': [
        '',
        '#ifdef IS_SIDE_VERTEX',
        '  vGradientFrac = positions.y;',
        '  vBaseMeters = elevations * positions.y;',
        '#else',
        '  vGradientFrac = 1.0;',
        '  vBaseMeters = elevations;',
        '#endif',
        ''
      ].join('\n'),
      'fs:#decl': '\nin float vGradientFrac;\nin float vBaseMeters;\n',
      'fs:DECKGL_FILTER_COLOR': [
        '',
        '  float gradMul = mix(' + bottom + ', 1.0, clamp(vGradientFrac, 0.0, 1.0));',
        '  float aoMul = mix(' + aoBottom + ', 1.0, smoothstep(0.0, ' + aoHeight + ', vBaseMeters));',
        '  color.rgb *= gradMul * aoMul;',
        ''
      ].join('\n')
    }
  };
};

function buildLightingEffect() {
  var amb = new deck.AmbientLight({ color: [255, 255, 255], intensity: 0.82 });
  sunLight = new deck.DirectionalLight({
    color: [255, 255, 255],
    intensity: 1.0,
    direction: [0.5, -0.5, -0.707],
    _shadow: true
  });
  lightingEffect = new deck.LightingEffect({ ambientLight: amb, sunLight: sunLight });
  lightingEffect.shadowColor = [0, 0, 0, 0.45];
  return lightingEffect;
}

function makeBuildingLayer() {
  return new deck.PolygonLayer({
    id: 'deck-buildings',
    data: deckBuildingData,
    extruded: true,
    getPolygon: function(d) { return d.polygon; },
    getElevation: function(d) { return d.height; },
    getFillColor: [255, 255, 255],
    material: { ambient: 1.0, diffuse: 0.85, shininess: 1, specularColor: [0, 0, 0] },
    getLineColor: [0, 0, 0, 0],
    parameters: { depthTest: true },
    extensions: [new BuildingShadingExtension()]
  });
}

function makeGroundLayer() {
  return new deck.PolygonLayer({
    id: 'deck-ground',
    data: deckGroundData,
    extruded: false,
    getPolygon: function(d) { return d.polygon; },
    getElevation: 0,
    getFillColor: [255, 255, 255, 0],
    getLineColor: [0, 0, 0, 0],
    material: { ambient: 1.0, diffuse: 0.0, shininess: 1, specularColor: [0, 0, 0] },
    parameters: { depthWriteEnabled: false }
  });
}

function deckLayers() {
  return [makeGroundLayer(), makeBuildingLayer()];
}

function buildingHeight(props) {
  var h = props.render_height || props.height || props.levels && props.levels * 3 || 0;
  return Number(h) || 0;
}

function ringsFromGeometry(geom) {
  if (!geom) return [];
  if (geom.type === 'Polygon') return [geom.coordinates[0]];
  if (geom.type === 'MultiPolygon') return geom.coordinates.map(function(poly) { return poly[0]; });
  return [];
}

function groundPolygonFromBounds() {
  var b = map.getBounds();
  var w = b.getWest(), s = b.getSouth(), e = b.getEast(), n = b.getNorth();
  var padX = (e - w) * 0.5, padY = (n - s) * 0.5;
  w -= padX; e += padX; s -= padY; n += padY;
  return [[w, s], [e, s], [e, n], [w, n], [w, s]];
}

function refreshDeckBuildings() {
  if (!deckOverlay) return;
  var def = getBasemapStyle(currentBasemap);
  if (!def.buildingRGB || map.getZoom() < 14) {
    deckBuildingData = [];
    deckGroundData = [];
    deckOverlay.setProps({ layers: deckLayers() });
    return;
  }
  var feats = [];
  try {
    feats = map.querySourceFeatures('openmaptiles', { sourceLayer: 'building' });
  } catch (e) {
    feats = [];
  }
  var seen = {};
  var rows = [];
  for (var i = 0; i < feats.length; i++) {
    var f = feats[i];
    var id = f.id != null ? f.id : (f.properties && f.properties['@id']);
    if (id != null) {
      if (seen[id]) continue;
      seen[id] = true;
    }
    var height = buildingHeight(f.properties || {});
    if (height <= 0) height = 3;
    var rings = ringsFromGeometry(f.geometry);
    for (var r = 0; r < rings.length; r++) {
      rows.push({ polygon: rings[r], height: height });
    }
  }
  deckBuildingData = rows;
  deckGroundData = rows.length ? [{ polygon: groundPolygonFromBounds() }] : [];
  deckOverlay.setProps({ layers: deckLayers() });
}

function scheduleDeckRefresh(force) {
  if (!force && (map.isMoving() || map.isZooming())) return;
  clearTimeout(deckRefreshTimer);
  deckRefreshTimer = setTimeout(refreshDeckBuildings, 120);
}

function hideNativeBuildingExtrusion() {
  var style = map.getStyle();
  if (!style || !style.layers) return;
  for (var i = 0; i < style.layers.length; i++) {
    var lyr = style.layers[i];
    if (lyr.type === 'fill-extrusion' && map.getLayer(lyr.id)) {
      map.setLayoutProperty(lyr.id, 'visibility', 'none');
    }
  }
}

function setupDeckOverlay() {
  if (deckOverlay) return;
  buildLightingEffect();
  deckOverlay = new deck.MapboxOverlay({
    interleaved: false,
    useDevicePixels: Math.min((window.devicePixelRatio || 1) * 1.5, 3),
    effects: [lightingEffect],
    layers: deckLayers()
  });
  map.addControl(deckOverlay);
  hideNativeBuildingExtrusion();
  scheduleDeckRefresh();
}

function setupMapLayers() {
  setupDeckOverlay();
  map.addSource('grid', { type: 'geojson', data: emptyFeatureCollection() });
  map.addLayer({
    id: 'grid-fill',
    type: 'fill',
    source: 'grid',
    layout: { visibility: 'none' },
    paint: {
      'fill-color': ['case', ['get', 'selected'], '#ffffff', ['get', 'cached'], '#f8fffd', '#ffffff'],
      'fill-opacity': ['case', ['get', 'selected'], ['case', ['get', 'cached'], 0.58, 0.54], ['get', 'cached'], 0.32, 0]
    }
  });
  map.addLayer({
    id: 'grid-line',
    type: 'line',
    source: 'grid',
    layout: { visibility: 'none' },
    paint: {
      'line-color': '#000000',
      'line-opacity': 0.25,
      'line-width': ['case', ['get', 'selected'], 2, 1]
    }
  });
  map.addSource('draw', { type: 'geojson', data: emptyFeatureCollection() });
  map.addLayer({
    id: 'draw-rect',
    type: 'line',
    source: 'draw',
    paint: { 'line-color': '#1f8a70', 'line-width': 2, 'line-dasharray': [2, 2] }
  });
  map.addSource('highlight', { type: 'geojson', data: emptyFeatureCollection() });
  map.addLayer({
    id: 'region-outline-glow',
    type: 'line',
    source: 'highlight',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#3b82f6',
      'line-blur': 6,
      'line-opacity': 0,
      'line-opacity-transition': { duration: 450, delay: 0 },
      'line-width': ['interpolate', ['linear'], ['zoom'], 3, 6, 8, 11, 14, 18]
    }
  });
  map.addLayer({
    id: 'region-outline',
    type: 'line',
    source: 'highlight',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#3b82f6',
      'line-opacity': 0,
      'line-opacity-transition': { duration: 450, delay: 0 },
      'line-width': ['interpolate', ['linear'], ['zoom'], 3, 2, 8, 4, 14, 6]
    }
  });
}

function setDrawData(fc) {
  var src = map.getSource('draw');
  if (src) src.setData(fc || emptyFeatureCollection());
}

function buildGridFeatureCollection() {
  var tiles = (lastGridData && lastGridData.tiles) ? lastGridData.tiles : [];
  return {
    type: 'FeatureCollection',
    features: tiles.map(function(tile) {
      var b = tileDisplayBbox(tile);
      return {
        type: 'Feature',
        properties: {
          tile_id: tile.tile_id,
          selected: !!selectedTileIds[tile.tile_id],
          cached: !!tile.cached
        },
        geometry: {
          type: 'Polygon',
          coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]]
        }
      };
    })
  };
}

function setGridData() {
  var src = map.getSource('grid');
  if (src) src.setData(buildGridFeatureCollection());
}

function rectFeatureCollection(a, b) {
  var w = Math.min(a.lng, b.lng), e = Math.max(a.lng, b.lng);
  var s = Math.min(a.lat, b.lat), n = Math.max(a.lat, b.lat);
  return {
    type: 'FeatureCollection',
    features: [{
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates: [[w, s], [e, s], [e, n], [w, n], [w, s]] }
    }]
  };
}

function makeBounds(a, b) {
  var w = Math.min(a.lng, b.lng), e = Math.max(a.lng, b.lng);
  var s = Math.min(a.lat, b.lat), n = Math.max(a.lat, b.lat);
  return {
    getWest: function() { return w; },
    getEast: function() { return e; },
    getSouth: function() { return s; },
    getNorth: function() { return n; }
  };
}

function armRectangleTool() {
  rectToolArmed = true;
  rectDragging = false;
  rectStart = null;
  if (map.dragPan) map.dragPan.disable();
  map.getCanvas().style.cursor = 'crosshair';
}

function disarmRectangleTool() {
  rectToolArmed = false;
  rectDragging = false;
  rectStart = null;
  if (map.dragPan) map.dragPan.enable();
  map.getCanvas().style.cursor = '';
  setDrawData(emptyFeatureCollection());
  updateMapToolButtons();
}

function bindRectangleDrag() {
  map.on('mousedown', function(e) {
    if (!rectToolArmed) return;
    rectDragging = true;
    rectStart = e.lngLat;
    setDrawData(rectFeatureCollection(rectStart, e.lngLat));
  });
  map.on('mousemove', function(e) {
    if (!rectDragging || !rectStart) return;
    setDrawData(rectFeatureCollection(rectStart, e.lngLat));
  });
  map.on('mouseup', function(e) {
    if (!rectDragging || !rectStart) return;
    var start = rectStart;
    var end = e.lngLat;
    rectDragging = false;
    rectStart = null;
    disarmRectangleTool();
    if (start.lng === end.lng && start.lat === end.lat) return;
    selectTilesByBounds(makeBounds(start, end));
  });
}

function forceEnglishLabels() {
  try { style = map.getStyle(); } catch (e) { return; }
  if (!style || !style.layers) return;
  var englishField = [
    'coalesce',
    ['get', 'name:en'],
    ['get', 'name:latin'],
    ['get', 'name']
  ];
  style.layers.forEach(function(lyr) {
    if (lyr.type !== 'symbol') return;
    if (!lyr.layout || lyr.layout['text-field'] === undefined) return;
    if (!map.getLayer(lyr.id)) return;
    try { map.setLayoutProperty(lyr.id, 'text-field', englishField); } catch (e) {}
  });
}

var WATER_DARK = '#838383';

function darkenWaterLayers() {
  var style;
  try { style = map.getStyle(); } catch (e) { return; }
  if (!style || !style.layers) return;
  var idHint = /water|ocean|river|lake|sea|marine/i;
  style.layers.forEach(function(lyr) {
    if (!map.getLayer(lyr.id)) return;
    var srcLayer = lyr['source-layer'];
    var isWater = srcLayer === 'water' || srcLayer === 'waterway' ||
                  (idHint.test(lyr.id) && !/waterway-?label|water-?name|building/i.test(lyr.id));
    if (!isWater) return;
    try {
      if (lyr.type === 'fill') {
        map.setPaintProperty(lyr.id, 'fill-color', WATER_DARK);
      } else if (lyr.type === 'line') {
        map.setPaintProperty(lyr.id, 'line-color', WATER_DARK);
      } else if (lyr.type === 'fill-extrusion') {
        map.setPaintProperty(lyr.id, 'fill-extrusion-color', WATER_DARK);
      }
    } catch (e) {}
  });
}

function applyGlobeProjection() {
  if (map.setProjection) map.setProjection({ type: 'globe' });
  if (map.setSky) {
    // 大气改用自定义 3D 半透明球壳层（atmosphere-shell custom layer）实现，
    // 原生 setSky 大气在本项目里观感像"地球高光"，这里关掉。
    map.setSky({
      'sky-color': '#05070d',
      'horizon-color': '#05070d',
      'fog-color': '#05070d',
      'sky-horizon-blend': 0.0,
      'horizon-fog-blend': 0.0,
      'fog-ground-blend': 0.0,
      'atmosphere-blend': 0.0
    });
  }
}

map.on('load', function() {
  setupMapLayers();
  mapReady = true;
  applyGlobeProjection();
  forceEnglishLabels();
  darkenWaterLayers();
  bindRectangleDrag();
  restoreRememberedSelection();
  scheduleGridLoad();
  cameraController.start();
  cameraController.setupViewToggle();
  requestAnimationFrame(function() {
    var el = document.getElementById('map');
    if (el) el.classList.add('map-ready');
  });
});

function setBasemapStyle(id) {
  if (!mapReady) return;
  if (id === currentBasemap) {
    return;
  }
  var target = getBasemapStyle(id);
  map.once('styledata', function() {
    setupMapLayers();
    setGridData();
    syncDrawnSelectionLayer();
    restoreBoundaryAfterStyle();
    hideNativeBuildingExtrusion();
    applyGlobeProjection();
    forceEnglishLabels();
    darkenWaterLayers();
    scheduleDeckRefresh();
  });
  map.setStyle(target.style);
  currentBasemap = target.id;
  updateBasemapMenu();
  log('底图风格已切换到「' + target.label + '」。', 'info');
}

function replayReveal(el) {
  if (!el) return;
  el.classList.remove('flat-conceal', 'flat-reveal');
  void el.offsetWidth;
  el.classList.add('flat-reveal');
}

function concealThenReveal(el, swap) {
  if (!el) { if (swap) swap(); return; }
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var alreadyOpen = !el.hidden;
  if (reduce || !alreadyOpen) {
    if (swap) swap();
    return;
  }
  el.classList.remove('flat-reveal');
  void el.offsetWidth;
  el.classList.add('flat-conceal');
  var done = function() {
    el.removeEventListener('animationend', done);
    if (swap) swap();
  };
  el.addEventListener('animationend', done);
}

function updateBasemapMenu() {
  var seg = document.getElementById('basemap-segment');
  if (!seg) return;
  var options = seg.querySelectorAll('.segmented-option');
  var thumb = seg.querySelector('.segmented-thumb');
  var activeNode = null;
  Array.prototype.forEach.call(options, function(node) {
    var on = node.dataset.styleId === currentBasemap;
    node.classList.toggle('active', on);
    node.setAttribute('aria-checked', on ? 'true' : 'false');
    if (on) activeNode = node;
  });
  if (thumb && activeNode) {
    thumb.style.width = activeNode.offsetWidth + 'px';
    thumb.style.transform = 'translateX(' + activeNode.offsetLeft + 'px)';
  }
}

function rectangleToolActive() {
  return rectToolArmed;
}

function updateMapToolButtons() {
  if (selectionToolButtons.grid) {
    selectionToolButtons.grid.classList.toggle('active', gridVisible);
    selectionToolButtons.grid.setAttribute('aria-pressed', gridVisible ? 'true' : 'false');
  }
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

function setGridVisible(visible) {
  gridVisible = !!visible;
  var value = gridVisible ? 'visible' : 'none';
  ['grid-fill', 'grid-line'].forEach(function(layerId) {
    if (map.getLayer(layerId)) map.setLayoutProperty(layerId, 'visibility', value);
  });
  var toolbar = document.getElementById('selection-tools');
  if (toolbar) toolbar.classList.toggle('drawer-open', gridVisible);
  var drawer = toolbar && toolbar.querySelector('.map-tool-drawer');
  if (drawer) drawer.setAttribute('aria-hidden', gridVisible ? 'false' : 'true');
  updateMapToolButtons();
}

function toggleGridVisible() {
  setGridVisible(!gridVisible);
}

function setPointSelectActive(active) {
  pointSelectActive = !!active;
  if (pointSelectActive && rectangleToolActive()) disarmRectangleTool();
  var container = map.getContainer();
  if (pointSelectActive) {
    container.classList.add('point-select-active');
  } else {
    container.classList.remove('point-select-active');
  }
  updateMapToolButtons();
}

function activateRectangleTool() {
  setPointSelectActive(false);
  if (!rectangleToolActive()) armRectangleTool();
  updateMapToolButtons();
}

function clearSelectionFromMapTool() {
  setPointSelectActive(false);
  if (rectangleToolActive()) disarmRectangleTool();
  clearSelection();
}

function bindSelectionTools() {
  selectionToolButtons = {
    grid: document.querySelector('.map-tool-grid'),
    rectangle: document.querySelector('.map-tool-rectangle'),
    point: document.querySelector('.map-tool-point'),
    clear: document.querySelector('.map-tool-clear')
  };
  if (selectionToolButtons.grid) {
    selectionToolButtons.grid.addEventListener('click', toggleGridVisible);
  }
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
  buildBasemapMenu();
  updateMapToolButtons();
  updateBasemapMenu();
}

function buildBasemapMenu() {
  var seg = document.getElementById('basemap-segment');
  if (!seg) return;
  seg.textContent = '';
  var thumb = document.createElement('span');
  thumb.className = 'segmented-thumb';
  seg.appendChild(thumb);
  BASEMAP_STYLES.forEach(function(item) {
    var opt = document.createElement('button');
    opt.type = 'button';
    opt.className = 'segmented-option';
    opt.setAttribute('role', 'radio');
    opt.dataset.styleId = item.id;
    opt.textContent = item.label;
    opt.addEventListener('click', function(e) {
      e.stopPropagation();
      setBasemapStyle(item.id);
    });
    seg.appendChild(opt);
  });
}
bindSelectionTools();

function shortSearchTitle(item) {
  var name = item.name || item.display_name || '';
  if (name) return name;
  var display = item.display_name || '';
  return display.split(',').slice(0, 2).join(', ') || '未知地点';
}

function focusSearchResult(item) {
  var lat = parseFloat(item.lat);
  var lon = parseFloat(item.lon);
  if (!isFinite(lat) || !isFinite(lon)) return;
  if (item.boundingbox && item.boundingbox.length === 4) {
    var south = parseFloat(item.boundingbox[0]);
    var north = parseFloat(item.boundingbox[1]);
    var west = parseFloat(item.boundingbox[2]);
    var east = parseFloat(item.boundingbox[3]);
    if (isFinite(south) && isFinite(north) && isFinite(west) && isFinite(east) && south < north && west < east) {
      map.fitBounds([[west, south], [east, north]], { padding: 40, maxZoom: 15 });
    } else {
      map.jumpTo({ center: [lon, lat], zoom: 13 });
    }
  } else {
    map.jumpTo({ center: [lon, lat], zoom: 13 });
  }
  setText('location-search-status', '已定位：' + shortSearchTitle(item) + '。现在可以点选或框选网格。');
  scheduleGridLoad();
}

function bindLocationSearch() {
  var form = document.getElementById('location-search-form');
  var input = document.getElementById('location-search-input');
  var btn = document.getElementById('location-search-btn');
  if (!form || !input) return;
  form.addEventListener('submit', function(event) {
    event.preventDefault();
    var q = input.value.trim();
    if (!q) {
      setText('location-search-status', '请输入国家、地区、城市或地址。');
      return;
    }
    setText('location-search-status', '正在搜索：' + q);
    if (btn) btn.disabled = true;
    fetch('/geocode?q=' + encodeURIComponent(q))
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (!d.ok) {
        setText('location-search-status', d.message || '搜索失败');
        return;
      }
      var items = d.results || [];
      if (!items.length) {
        setText('location-search-status', '没有找到匹配地点。');
        return;
      }
      focusSearchResult(items[0]);
    })
    .catch(function(e) {
      setText('location-search-status', '搜索失败：' + e);
    })
    .finally(function() {
      if (btn) btn.disabled = false;
    });
  });
}

bindLocationSearch();

map.on('click', function(e) {
  if (!pointSelectActive) return;
  selectTileByLatLng(e.lngLat);
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
    note.style.color = 'var(--accent)';
  } else {
    note.textContent = '文件不存在: ' + value;
    note.style.color = 'var(--accent)';
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
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    if (!d.ok && note) {
      note.textContent = d.message || '保存失败';
      note.style.color = 'var(--accent)';
    }
    if (refreshAfter) refreshServiceState();
    return d;
  })
  .catch(function(e) {
    if (note) {
      note.textContent = '保存失败: ' + e;
      note.style.color = 'var(--accent)';
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
  if (available) setDccSoftwareSwitch('houdini', true);
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
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    if (!d.ok) {
      var note = document.getElementById('houdini-path-note');
      if (note) {
        note.textContent = d.message || '启动失败';
        note.style.color = 'var(--accent)';
      }
      refreshServiceState();
      return;
    }
    setDccSoftwareSwitch('houdini', true);
    pollHoudiniAfterOpen(8);
  })
  .catch(function(e) {
    var note = document.getElementById('houdini-path-note');
    if (note) {
      note.textContent = '启动失败: ' + e;
      note.style.color = 'var(--accent)';
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

function bboxCenter(bbox) {
  if (!bbox || bbox.length !== 4) return null;
  return [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2];
}

function findRegionById(items, id) {
  items = items || [];
  for (var i = 0; i < items.length; i++) {
    if (items[i].id === id) return items[i];
  }
  return null;
}

function setActiveChildByIndex(host, index) {
  if (!host) return;
  Array.prototype.forEach.call(host.children, function(node, i) {
    node.classList.toggle('active', i === index);
  });
}

function showDefaultCityPreview() {
  var country = findRegionById(regionData, 'sg');
  if (!country) return false;
  var cities = country.cities || [];
  var city = findRegionById(country.cities || [], 'central');
  if (!city) return false;
  activeCountryId = country.id;
  setActiveChildByIndex(document.getElementById('region-countries'), regionData.indexOf(country));
  renderCities(cities);
  setActiveChildByIndex(document.getElementById('region-cities'), cities.indexOf(city));
  loadBoundary(city.osmId);
  var target = (city.landmark && city.landmark.length === 2) ? city.landmark : bboxCenter(city.bbox);
  if (!target) return false;
  cityPreviewActive = true;
  flyTo3DCity(target[0], target[1], city.landmark_zoom || 15);
  return true;
}

function showGlobalOverview() {
  cityPreviewActive = false;
  cameraController.flyToWorld();
}

function flyToBbox(bbox, maxZoom) {
  cameraController.fitBounds2D(bbox, maxZoom);
}

function flyTo3DCity(lng, lat, zoom) {
  cameraController.flyToCity(lng, lat, zoom);
}

function exit3DTo2D() {
  cameraController.exitTo2D();
}

function enter3DInPlace() {
  cameraController.enter3DInPlace();
}

function syncHoudiniCameraToCity() {
  var view = lastCityView;
  if (!view && regionData) {
    var country = findRegionById(regionData, 'sg');
    var city = country ? findRegionById(country.cities || [], 'central') : null;
    if (city && city.bbox) view = { bbox: city.bbox, maxZoom: 12 };
  }
  if (!view) return false;
  cityPreviewActive = false;
  map.once('moveend', scheduleGridLoad);
  flyToBbox(view.bbox, view.maxZoom);
  return true;
}

function setupViewToggle() {
  cameraController.setupViewToggle();
}

function syncViewToggle() {
  cameraController.syncViewToggle();
}

function updateWorkspaceButtons(workspaceId) {
  var buttons = document.querySelectorAll('[data-workspace-target]');
  Array.prototype.forEach.call(buttons, function(button) {
    var active = button.dataset.workspaceTarget === workspaceId;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  var dccSummary = document.querySelector('.dcc-bridge-summary');
  if (dccSummary) dccSummary.classList.remove('active');
}

function syncActionPanelContent(workspaceId) {
  var panels = document.querySelectorAll('[data-action-panel-content]');
  Array.prototype.forEach.call(panels, function(panel) {
    panel.hidden = panel.dataset.actionPanelContent !== workspaceId;
  });
}

function syncActionPanelToggle() {
  var workspace = document.getElementById('workspace');
  var actionPanel = document.getElementById('action-panel');
  var toggle = document.getElementById('action-panel-toggle');
  var collapsed = !!actionPanelCollapsed;
  if (workspace) workspace.dataset.actionPanelCollapsed = collapsed ? 'true' : 'false';
  if (actionPanel) actionPanel.hidden = collapsed;
  if (!toggle) return;
  toggle.hidden = false;
  toggle.classList.toggle('is-collapsed', collapsed);
  toggle.setAttribute('aria-pressed', collapsed ? 'true' : 'false');
  toggle.setAttribute('aria-label', collapsed ? '展开右栏' : '收起右栏');
  toggle.title = collapsed ? '展开右栏' : '收起右栏';
}

function setActionPanelCollapsed(collapsed) {
  actionPanelCollapsed = !!collapsed;
  syncActionPanelToggle();
  requestAnimationFrame(function() {
    if (map && map.resize) map.resize();
    if (activeWorkspaceId === 'houdini') scheduleGridLoad();
    if (typeof scheduleDeckRefresh === 'function') scheduleDeckRefresh(true);
  });
}

function bindActionPanelToggle() {
  var toggle = document.getElementById('action-panel-toggle');
  if (!toggle) return;
  toggle.addEventListener('click', function() {
    setActionPanelCollapsed(!actionPanelCollapsed);
  });
  syncActionPanelToggle();
}

function setHoudiniOutlineHeight(height) {
  var panel = document.querySelector('[data-action-panel-content="houdini"]');
  var resizer = document.getElementById('houdini-side-resizer');
  if (!panel || !resizer) return;
  var rect = panel.getBoundingClientRect();
  if (rect.height <= 0) return;
  var resizerHeight = resizer.getBoundingClientRect().height || 6;
  var minHeight = 150;
  var maxHeight = Math.max(minHeight, rect.height - resizerHeight - 200);
  var nextHeight = Math.max(minHeight, Math.min(maxHeight, height));
  panel.style.setProperty('--houdini-outline-height', Math.round(nextHeight) + 'px');
  resizer.setAttribute('aria-valuemin', String(minHeight));
  resizer.setAttribute('aria-valuemax', String(Math.round(maxHeight)));
  resizer.setAttribute('aria-valuenow', String(Math.round(nextHeight)));
}

function setHoudiniOutlineHeightFromPointer(event) {
  var panel = document.querySelector('[data-action-panel-content="houdini"]');
  var resizer = document.getElementById('houdini-side-resizer');
  if (!panel || !resizer) return;
  var rect = panel.getBoundingClientRect();
  var resizerHeight = resizer.getBoundingClientRect().height || 6;
  setHoudiniOutlineHeight(rect.bottom - event.clientY - resizerHeight / 2);
}

function finishHoudiniSideResize(event) {
  if (!houdiniSideResizeState) return;
  var resizer = document.getElementById('houdini-side-resizer');
  if (resizer && resizer.releasePointerCapture && event && event.pointerId === houdiniSideResizeState.pointerId) {
    try { resizer.releasePointerCapture(event.pointerId); } catch (e) {}
  }
  houdiniSideResizeState = null;
  document.body.classList.remove('is-resizing-game-side');
}

function bindHoudiniSideResize() {
  var resizer = document.getElementById('houdini-side-resizer');
  var outline = document.getElementById('houdini-run-outline');
  if (!resizer || !outline) return;
  resizer.addEventListener('pointerdown', function(event) {
    if (event.button !== 0) return;
    event.preventDefault();
    houdiniSideResizeState = { pointerId: event.pointerId };
    document.body.classList.add('is-resizing-game-side');
    if (resizer.setPointerCapture) resizer.setPointerCapture(event.pointerId);
    setHoudiniOutlineHeightFromPointer(event);
  });
  window.addEventListener('pointermove', function(event) {
    if (!houdiniSideResizeState) return;
    event.preventDefault();
    setHoudiniOutlineHeightFromPointer(event);
  });
  window.addEventListener('pointerup', finishHoudiniSideResize);
  window.addEventListener('pointercancel', finishHoudiniSideResize);
  resizer.addEventListener('keydown', function(event) {
    var step = 20;
    var current = outline.getBoundingClientRect().height;
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setHoudiniOutlineHeight(current + step);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setHoudiniOutlineHeight(current - step);
    } else if (event.key === 'Home') {
      event.preventDefault();
      setHoudiniOutlineHeight(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      setHoudiniOutlineHeight(Number.MAX_SAFE_INTEGER);
    }
  });
}

function bindAccountMenu() {
  var menu = document.querySelector('.account-menu');
  if (!menu) return;
  document.addEventListener('click', function(event) {
    if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') menu.open = false;
  });
}

function initialWorkspaceId() {
  if (!window.sessionStorage) return activeWorkspaceId;
  try {
    var storedWorkspace = window.sessionStorage.getItem(frontendRefreshWorkspaceKey);
    window.sessionStorage.removeItem(frontendRefreshWorkspaceKey);
    if (storedWorkspace && WORKSPACE_KINDS[storedWorkspace]) return storedWorkspace;
  } catch (e) {}
  return activeWorkspaceId;
}

function bindFrontendRefresh() {
  var refreshButton = document.getElementById('frontend-refresh-button');
  var restartButton = document.getElementById('backend-restart-button');
  if (!refreshButton && !restartButton) return;
  function reloadWithCacheBust() {
    var url = new URL(window.location.href);
    url.searchParams.set('refresh', String(Date.now()));
    window.location.replace(url.toString());
  }
  function rememberWorkspace() {
    try {
      sessionStorage.setItem(frontendRefreshWorkspaceKey, activeWorkspaceId);
    } catch (e) {}
  }
  if (refreshButton) {
    refreshButton.addEventListener('click', function() {
      rememberWorkspace();
      reloadWithCacheBust();
    });
  }
  if (restartButton) {
    restartButton.addEventListener('click', function() {
      rememberWorkspace();
      clearDccPathCache();
      restartButton.classList.add('is-refreshing');
      restartButton.disabled = true;
      fetch('/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      })
      .catch(function() {})
      .finally(function() {
        setTimeout(function() {
          restartButton.classList.remove('is-refreshing');
          restartButton.disabled = false;
        }, 2500);
      });
    });
  }
}

function setWorkspace(id) {
  var nextWorkspace = WORKSPACE_KINDS[id] ? id : 'houdini';
  var workspaceKind = WORKSPACE_KINDS[nextWorkspace];
  activeWorkspaceId = nextWorkspace;
  var workspace = document.getElementById('workspace');
  var mapShell = document.getElementById('map-shell');
  var gameWorkbench = document.getElementById('game-workbench');
  var isHoudini = workspaceKind === 'houdini';
  var showsMap = workspaceKind !== 'game';
  if (workspace) workspace.dataset.workspaceKind = workspaceKind;
  if (mapShell) mapShell.hidden = !showsMap;
  syncActionPanelContent(nextWorkspace);
  syncActionPanelToggle();
  if (gameWorkbench) gameWorkbench.hidden = workspaceKind !== 'game';
  if (window.VC_GAME_WORKBENCH) {
    if (workspaceKind === 'game') {
      window.VC_GAME_WORKBENCH.init();
    }
    window.VC_GAME_WORKBENCH.setActive(workspaceKind === 'game');
  }
  if (!isHoudini) {
    setGridVisible(false);
    setPointSelectActive(false);
    if (rectangleToolActive()) disarmRectangleTool();
  }
  updateWorkspaceButtons(nextWorkspace);
  if (showsMap) {
    requestAnimationFrame(function() {
      if (map && map.resize) map.resize();
      if (isHoudini) {
        setGridVisible(true);
        syncHoudiniCameraToCity();
        scheduleGridLoad();
      }
      if (typeof scheduleDeckRefresh === 'function') scheduleDeckRefresh(true);
      if (nextWorkspace === 'city-preview') showDefaultCityPreview();
      if (nextWorkspace === 'news') showGlobalOverview();
      else if (cityPreviewActive && nextWorkspace !== 'city-preview' && nextWorkspace !== 'houdini' && showsMap) {
        cityPreviewActive = false;
        exit3DTo2D();
      }
    });
  }
}

function bindWorkspaceSwitching() {
  var buttons = document.querySelectorAll('[data-workspace-target]');
  Array.prototype.forEach.call(buttons, function(button) {
    button.addEventListener('click', function() {
      setWorkspace(button.dataset.workspaceTarget);
    });
  });
}

var boundaryCache = {};
var lastBoundaryFC = null;
var requestedBoundaryKey = null;
var GLOW_OPACITY = 0.5;

function setHighlightData(fc) {
  var src = map.getSource('highlight');
  if (src) src.setData(fc || emptyFeatureCollection());
}

function setHighlightOpacity(on) {
  if (map.getLayer('region-outline-glow')) {
    map.setPaintProperty('region-outline-glow', 'line-opacity', on ? GLOW_OPACITY : 0);
  }
  if (map.getLayer('region-outline')) {
    map.setPaintProperty('region-outline', 'line-opacity', on ? 1 : 0);
  }
}

function showBoundary(fc) {
  lastBoundaryFC = fc || null;
  setHighlightData(fc);
  setHighlightOpacity(!!fc);
}

function hideBoundary() {
  lastBoundaryFC = null;
  requestedBoundaryKey = null;
  setHighlightOpacity(false);
}

function restoreBoundaryAfterStyle() {
  if (lastBoundaryFC) {
    setHighlightData(lastBoundaryFC);
    setHighlightOpacity(true);
  }
}

function loadBoundary(osmId) {
  if (!osmId) {
    hideBoundary();
    return;
  }
  requestedBoundaryKey = String(osmId);
  var cached = boundaryCache[osmId];
  if (cached) {
    showBoundary(cached);
    return;
  }
  fetch('/boundary?osm_type=R&osm_id=' + encodeURIComponent(osmId))
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (requestedBoundaryKey !== String(osmId)) return;
    if (!d || !d.ok || !d.geojson) {
      hideBoundary();
      return;
    }
    var fc = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: d.geojson }] };
    boundaryCache[osmId] = fc;
    showBoundary(fc);
  })
  .catch(function() {
    if (requestedBoundaryKey !== String(osmId)) return;
    hideBoundary();
  });
}

var regionData = null;
var activeCountryId = null;

function loadRegionNav() {
  fetch('/area-picker/regions.json?v=' + window.VC_CONFIG.version)
  .then(function(r) { return r.json(); })
  .then(function(d) {
    regionData = d && d.countries ? d.countries : [];
    renderCountries();
    if (activeWorkspaceId === 'city-preview') showDefaultCityPreview();
    else if (activeWorkspaceId === 'houdini') syncHoudiniCameraToCity();
  })
  .catch(function() {
    regionData = [];
  });
}

function renderCountries() {
  var host = document.getElementById('region-countries');
  if (!host) return;
  host.textContent = '';
  regionData.forEach(function(country) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'region-item flat-item';
    btn.setAttribute('role', 'listitem');
    btn.textContent = country.name;
    btn.title = '定位到 ' + country.name;
    btn.addEventListener('click', function() {
      selectCountry(country, btn);
    });
    host.appendChild(btn);
  });
}

function selectCountry(country, btn) {
  activeCountryId = country.id;
  var host = document.getElementById('region-countries');
  if (host) {
    Array.prototype.forEach.call(host.children, function(node) {
      node.classList.toggle('active', node === btn);
    });
  }
  loadBoundary(country.osmId);
  flyToBbox(country.bbox, 7);
  var citiesHost = document.getElementById('region-cities');
  concealThenReveal(citiesHost, function() {
    renderCities(country.cities || []);
  });
}

function renderCities(cities) {
  var host = document.getElementById('region-cities');
  if (!host) return;
  host.textContent = '';
  if (!cities.length) {
    host.hidden = true;
    return;
  }
  cities.forEach(function(city) {
    var row = document.createElement('div');
    row.className = 'region-city-row';
    row.setAttribute('role', 'listitem');

    var nameBtn = document.createElement('button');
    nameBtn.type = 'button';
    nameBtn.className = 'region-name-btn';
    nameBtn.textContent = city.name;
    nameBtn.title = '定位到 ' + city.name;
    nameBtn.addEventListener('click', function() {
      Array.prototype.forEach.call(host.children, function(node) {
        node.classList.toggle('active', node === row);
      });
      loadBoundary(city.osmId);
      lastCityView = { bbox: city.bbox, maxZoom: 12 };
      flyToBbox(lastCityView.bbox, lastCityView.maxZoom);
    });

    var buildBtn = document.createElement('button');
    buildBtn.type = 'button';
    buildBtn.className = 'region-build-btn';
    buildBtn.title = city.name + ' 3D 巡游';
    buildBtn.setAttribute('aria-label', city.name + ' 3D 巡游');
    buildBtn.innerHTML = '<svg class="region-build-icon" aria-hidden="true" viewBox="0 0 24 24"><path d="M3 21h18"></path><path d="M5 21V7l8-4v18"></path><path d="M19 21V11l-6-4"></path><path d="M9 9h.01"></path><path d="M9 13h.01"></path><path d="M9 17h.01"></path></svg>';
    buildBtn.addEventListener('click', function() {
      Array.prototype.forEach.call(host.children, function(node) {
        node.classList.toggle('active', node === row);
      });
      var target = (city.landmark && city.landmark.length === 2)
        ? city.landmark
        : bboxCenter(city.bbox);
      if (!target) return;
      loadBoundary(city.osmId);
      cityPreviewActive = true;
      flyTo3DCity(target[0], target[1], city.landmark_zoom || 15);
    });

    row.appendChild(nameBtn);
    row.appendChild(buildBtn);
    host.appendChild(row);
  });
  host.hidden = false;
  replayReveal(host);
}

function refreshServiceState() {
  fetch('/health')
  .then(function(r) { return r.json(); })
  .then(function(d) {
    setHoudiniBadge(!!d.houdini_available, d.houdini_asset);
    updateSoftwarePath(d.software_paths);
    updateDccSoftwarePaths(d.software_paths);
    updateExportButton(!!d.export_available, !!d.running);
    updateSelectionButtons(!!d.running);
    updateRunStatusFromHealth(d);
    refreshDataSources();
  })
  .catch(function() {
    setHoudiniBadge(false, null);
    setRunStatus('off', '离线', 0, '状态服务不可用');
  });
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

function tileDisplayBbox(tile) {
  return tile.display_bbox || tile.bbox;
}

function sortedUniqueNumbers(values) {
  var seen = {};
  values.forEach(function(value) {
    var number = Number(value);
    if (Number.isFinite(number)) seen[String(number)] = number;
  });
  return Object.keys(seen).map(function(key) { return seen[key]; }).sort(function(a, b) { return a - b; });
}

function assignDisplayGridBounds(tiles) {
  if (!tiles || !tiles.length) return;
  var eastings = sortedUniqueNumbers(tiles.map(function(tile) { return tile.easting; }));
  var northings = sortedUniqueNumbers(tiles.map(function(tile) { return tile.northing; }));
  if (!eastings.length || !northings.length) return;

  var colIndex = {};
  var rowIndex = {};
  eastings.forEach(function(value, index) { colIndex[String(value)] = index; });
  northings.forEach(function(value, index) { rowIndex[String(value)] = index; });

  var west = Math.min.apply(null, tiles.map(function(tile) { return tile.bbox[0]; }));
  var south = Math.min.apply(null, tiles.map(function(tile) { return tile.bbox[1]; }));
  var east = Math.max.apply(null, tiles.map(function(tile) { return tile.bbox[2]; }));
  var north = Math.max.apply(null, tiles.map(function(tile) { return tile.bbox[3]; }));
  var lonStep = (east - west) / eastings.length;
  var latStep = (north - south) / northings.length;
  if (!Number.isFinite(lonStep) || !Number.isFinite(latStep) || lonStep <= 0 || latStep <= 0) {
    tiles.forEach(function(tile) { tile.display_bbox = tile.bbox; });
    return;
  }

  tiles.forEach(function(tile) {
    var col = colIndex[String(Number(tile.easting))];
    var row = rowIndex[String(Number(tile.northing))];
    if (col === undefined || row === undefined) {
      tile.display_bbox = tile.bbox;
      return;
    }
    tile.display_bbox = [
      west + col * lonStep,
      south + row * latStep,
      west + (col + 1) * lonStep,
      south + (row + 1) * latStep
    ];
  });
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
    if (el) el.textContent = '尚未框选网格';
    setText('area-id-chip', '未选择区域');
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
  if (el) {
    el.textContent =
      selection.selection_id + '\n' +
      selection.cols + ' x ' + selection.rows + ' 格 · ' +
      formatKm(selection.width_m) + ' x ' + formatKm(selection.height_m) + ' · ' + cacheText + '\n' +
      bboxText;
  }
  setText('area-id-chip', selection.selection_id);
  updateSelectionButtons(false);
  updateMapToolButtons();
}

function syncDrawnSelectionLayer() {
  setDrawData(emptyFeatureCollection());
}

function refreshTileStyles() {
  setGridData();
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
    return bboxIntersects(bounds, tileDisplayBbox(tile));
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
    var b = tileDisplayBbox(tile);
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
  setDrawData(emptyFeatureCollection());
  clearPersistedSelection();
  updateTileDisplay();
  refreshTileStyles();
  setRunStatus('warn', '待命', 0, '等待选择区域');
}

function renderGrid(data) {
  if (!data) {
    lastGridData = null;
    setGridData();
    return;
  }
  lastGridData = data;
  if (data.truncated) {
    setGridData();
    return;
  }
  assignDisplayGridBounds(data.tiles);
  setGridData();
  restorePendingSelection();
}

function loadGrid() {
  if (!mapReady) {
    scheduleGridLoad();
    return;
  }
  var canvas = map.getCanvas();
  if (!canvas || canvas.width <= 0 || canvas.height <= 0) {
    scheduleGridLoad();
    return;
  }
  var b = map.getBounds();
  if (!(b.getWest() < b.getEast() && b.getSouth() < b.getNorth())) {
    scheduleGridLoad();
    return;
  }
  var req = ++gridRequestId;
  var url = '/tiles?west=' + encodeURIComponent(b.getWest()) +
    '&south=' + encodeURIComponent(b.getSouth()) +
    '&east=' + encodeURIComponent(b.getEast()) +
    '&north=' + encodeURIComponent(b.getNorth());
  fetch(url)
  .then(function(r) { return r.json(); })
  .then(function(data) {
    if (req !== gridRequestId) return;
    renderGrid(data);
  })
  .catch(function(e) {
    log('[错误] 网格加载失败: ' + e, 'err');
  });
}

function scheduleGridLoad() {
  if (activeWorkspaceId !== 'houdini') return;
  clearTimeout(gridTimer);
  gridTimer = setTimeout(loadGrid, 40);
}

map.on('moveend', scheduleGridLoad);
map.on('zoomend', scheduleGridLoad);
map.on('moveend', function() {
  // City orbit only rotates bearing; avoid starving debounced building refresh.
  if (cameraController && cameraController.isCityOrbitActive()) return;
  scheduleDeckRefresh(true);
});
map.on('zoomend', function() { scheduleDeckRefresh(true); });
map.on('sourcedata', function(e) {
  if (e.sourceId === 'openmaptiles' && e.isSourceLoaded) scheduleDeckRefresh();
});
window.addEventListener('resize', function() {
  if (WORKSPACE_KINDS[activeWorkspaceId] === 'game') return;
  map.resize();
  if (activeWorkspaceId === 'houdini') scheduleGridLoad();
  if (typeof scheduleDeckRefresh === 'function') scheduleDeckRefresh(true);
});

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

function applyStatus(d) {
  (function() {
    updateRunStatusFromHealth(d);
    updateSoftwarePath(d.software_paths);

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
    updateExportButton(!!d.export_available, !!d.export_running || !!d.running);
    setHoudiniBadge(!!d.houdini_available, d.houdini_asset);
    updateDccSoftwarePaths(d.software_paths);
    updateSelectionButtons(!!d.running);

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

function dccSoftwareId(row) {
  return row ? (row.getAttribute('data-dcc-id') || '').trim() : '';
}

function dccSoftwarePathKey(row) {
  var softwareId = dccSoftwareId(row);
  return softwareId ? softwareId + '_exe' : '';
}

function dccPathStorageKey(row) {
  return dccPathCachePrefix + dccSoftwareId(row);
}

function getCachedDccPath(row) {
  try {
    return localStorage.getItem(dccPathStorageKey(row)) || '';
  } catch (e) {
    return '';
  }
}

function setCachedDccPath(row, value) {
  try {
    if (value) localStorage.setItem(dccPathStorageKey(row), value);
    else localStorage.removeItem(dccPathStorageKey(row));
  } catch (e) {}
}

function clearDccPathCache() {
  try {
    var keys = [];
    for (var i = 0; i < localStorage.length; i++) {
      var key = localStorage.key(i);
      if (key && key.indexOf(dccPathCachePrefix) === 0) keys.push(key);
    }
    keys.forEach(function(key) {
      localStorage.removeItem(key);
    });
  } catch (e) {}
  document.querySelectorAll('.dcc-option-row').forEach(function(row) {
    var input = row.querySelector('.dcc-path-input');
    if (input) input.value = '';
    row.classList.remove('has-path');
    closeDccPathEditor(row);
  });
}

function updateDccSoftwarePaths(paths) {
  if (!paths) return;
  document.querySelectorAll('.dcc-option-row').forEach(function(row) {
    var input = row.querySelector('.dcc-path-input');
    var key = dccSoftwarePathKey(row);
    if (!input || !key) return;
    var value = paths[key] || getCachedDccPath(row);
    if (document.activeElement !== input) input.value = value;
    row.classList.toggle('has-path', !!value);
  });
}

function setDccSoftwareSwitch(softwareId, enabled) {
  var row = document.querySelector('.dcc-option-row[data-dcc-id="' + softwareId + '"]');
  var toggle = row ? row.querySelector('.dcc-toggle') : null;
  if (!row || !toggle) return;
  toggle.classList.toggle('is-on', enabled);
  toggle.setAttribute('aria-pressed', enabled ? 'true' : 'false');
  row.classList.toggle('is-enabled', enabled);
}

function saveDccSoftwarePath(row) {
  var input = row ? row.querySelector('.dcc-path-input') : null;
  var softwareId = dccSoftwareId(row);
  if (!input || !softwareId) return Promise.resolve({ ok: false });
  var value = input.value.trim();
  setCachedDccPath(row, value);
  row.classList.toggle('has-path', !!value);
  return fetch('/software-paths', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: softwareId, path: value })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    if (d.ok) row.classList.toggle('has-path', !!input.value.trim());
    return d;
  });
}

function closeDccPathEditor(row) {
  var pathBtn = row ? row.querySelector('.dcc-path-btn') : null;
  var editor = row ? row.querySelector('.dcc-path-editor') : null;
  if (pathBtn) {
    pathBtn.classList.remove('is-open');
    pathBtn.setAttribute('aria-expanded', 'false');
  }
  if (editor) editor.hidden = true;
}

function saveAndCloseDccPathEditor(row) {
  if (!row) return;
  saveDccSoftwarePath(row).then(function(d) {
    if (!d || d.ok) closeDccPathEditor(row);
  });
}

function openDccSoftware(row, toggle) {
  var input = row ? row.querySelector('.dcc-path-input') : null;
  var softwareId = dccSoftwareId(row);
  if (!row || !toggle || !softwareId) return;
  toggle.disabled = true;
  fetch('/open-software', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: softwareId, path: input ? input.value : '' })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    var ok = !!d.ok;
    setDccSoftwareSwitch(softwareId, ok);
    if (!ok && input) {
      var pathBtn = row.querySelector('.dcc-path-btn');
      var editor = row.querySelector('.dcc-path-editor');
      input.title = d.message || '软件启动失败';
      if (pathBtn) {
        pathBtn.classList.add('is-open');
        pathBtn.setAttribute('aria-expanded', 'true');
      }
      if (editor) editor.hidden = false;
      input.focus();
    }
  })
  .catch(function(e) {
    toggle.classList.remove('is-on');
    toggle.setAttribute('aria-pressed', 'false');
    row.classList.remove('is-enabled');
    if (input) input.title = '软件启动失败: ' + e;
  })
  .finally(function() {
    toggle.disabled = false;
  });
}

function closeDccSoftware(row, toggle) {
  var softwareId = dccSoftwareId(row);
  if (!row || !toggle || !softwareId) return;
  toggle.disabled = true;
  fetch('/close-software', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ software_id: softwareId })
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.software_paths) {
      updateSoftwarePath(d.software_paths);
      updateDccSoftwarePaths(d.software_paths);
    }
    setDccSoftwareSwitch(softwareId, !d.ok);
    if (!d.ok) toggle.title = d.message || '软件关闭失败';
  })
  .catch(function(e) {
    setDccSoftwareSwitch(softwareId, true);
    toggle.title = '软件关闭失败: ' + e;
  })
  .finally(function() {
    toggle.disabled = false;
  });
}

function bindDccBridgeControls() {
  var panel = document.querySelector('.dcc-bridge-options');
  if (!panel) return;
  var bridge = panel.closest('.dcc-bridge-panel');
  var summary = bridge ? bridge.querySelector('.dcc-bridge-summary') : null;
  if (bridge && summary) {
    bridge.addEventListener('toggle', function() {
      if (bridge.open) {
        updateWorkspaceButtons('');
        summary.classList.add('active');
      } else {
        updateWorkspaceButtons(activeWorkspaceId);
      }
    });
  }
  document.addEventListener('pointerdown', function(event) {
    if (bridge && bridge.open && !bridge.contains(event.target)) bridge.open = false;
    var keepRow = event.target.closest('.dcc-option-row');
    panel.querySelectorAll('.dcc-option-row').forEach(function(row) {
      if (row !== keepRow && row.querySelector('.dcc-path-editor:not([hidden])')) {
        saveAndCloseDccPathEditor(row);
      }
    });
  });
  panel.addEventListener('click', function(event) {
    var toggle = event.target.closest('.dcc-toggle');
    if (toggle && panel.contains(toggle)) {
      var row = toggle.closest('.dcc-option-row');
      if (toggle.classList.contains('is-on')) closeDccSoftware(row, toggle);
      else openDccSoftware(row, toggle);
      return;
    }

    var pathBtn = event.target.closest('.dcc-path-btn');
    if (pathBtn && panel.contains(pathBtn)) {
      var pathRow = pathBtn.closest('.dcc-option-row');
      var editor = pathRow ? pathRow.querySelector('.dcc-path-editor') : null;
      var open = pathBtn.getAttribute('aria-expanded') !== 'true';
      pathBtn.classList.toggle('is-open', open);
      pathBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (editor) {
        editor.hidden = !open;
        var pathInput = editor.querySelector('.dcc-path-input');
        if (open && pathInput) pathInput.focus();
      }
      return;
    }

    var install = event.target.closest('.dcc-install-btn');
    if (!install || !panel.contains(install)) return;
    var installed = install.getAttribute('aria-pressed') !== 'true';
    var installRow = install.closest('.dcc-option-row');
    if (installRow) installRow.classList.toggle('is-installed', installed);
    install.classList.toggle('is-installed', installed);
    install.setAttribute('aria-pressed', installed ? 'true' : 'false');
    install.textContent = installed ? '已安装' : '安装';
  });
  panel.addEventListener('change', function(event) {
    var input = event.target.closest('.dcc-path-input');
    if (!input || !panel.contains(input)) return;
    var row = input.closest('.dcc-option-row');
    if (!row) return;
    saveDccSoftwarePath(row);
  });
  panel.addEventListener('input', function(event) {
    var input = event.target.closest('.dcc-path-input');
    if (!input || !panel.contains(input)) return;
    var row = input.closest('.dcc-option-row');
    if (row) row.classList.toggle('has-path', !!input.value.trim());
  });
  panel.addEventListener('keydown', function(event) {
    var input = event.target.closest('.dcc-path-input');
    if (!input || !panel.contains(input) || event.key !== 'Enter') return;
    event.preventDefault();
    saveAndCloseDccPathEditor(input.closest('.dcc-option-row'));
  });
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

refreshServiceState();
refreshDataSources();
loadRegionNav();
bindWorkspaceSwitching();
bindActionPanelToggle();
bindHoudiniSideResize();
bindDccBridgeControls();
bindAccountMenu();
bindFrontendRefresh();
setWorkspace(initialWorkspaceId());
startPageSession();
