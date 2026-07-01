// Domain: map-bootstrap
// Owns: MapLibre bootstrap, global map state, region navigation, city preview, and page session lifecycle.
// AI handoff: For base map, city camera, region boundary, or page session issues, start here after checking focused modules.
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
var dccPathCachePrefix = 'worldbuilder.dcc.path.';
var legacyDccPathCachePrefix = 'virtualcity.dcc.path.';
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
var WORLD_GEOJSON_URL = '/area-picker/world_countries.json?v=' + window.VC_CONFIG.version;
var WORLD_OCEAN_COLOR = '#838383';
var WORLD_LAND_COLOR = '#f8f4f0';
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
var map = null;
var cameraController = null;
var activeMapContext = null;
var mapContexts = {};
var viewToggleBound = false;

function getBasemapStyle(id) {
  for (var i = 0; i < BASEMAP_STYLES.length; i++) {
    if (BASEMAP_STYLES[i].id === id) return BASEMAP_STYLES[i];
  }
  return BASEMAP_STYLES[0];
}

function getNextBasemapStyle(id) {
  var current = getBasemapStyle(id);
  var index = BASEMAP_STYLES.indexOf(current);
  return BASEMAP_STYLES[(index + 1) % BASEMAP_STYLES.length];
}

function mapContainerIdForWorkspace(workspaceId) {
  if (workspaceId === 'city-preview') return 'map-zone';
  if (workspaceId === 'houdini') return 'map-houdini';
  return 'map-news';
}

function createMapContext(workspaceId) {
  var ctx = {
    workspaceId: workspaceId,
    currentBasemap: 'positron',
    mapReady: false,
    deckOverlay: null,
    deckBuildingData: [],
    deckGroundData: [],
    deckRefreshTimer: null,
    sunLight: null,
    lightingEffect: null,
    worldLayersRemoved: false,
    lastBoundaryFC: null,
    requestedBoundaryKey: null
  };
  ctx.map = new maplibregl.Map({
    container: mapContainerIdForWorkspace(workspaceId),
    style: getBasemapStyle(ctx.currentBasemap).style,
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
  ctx.map.touchZoomRotate.disableRotation();
  if (ctx.map.scrollZoom) ctx.map.scrollZoom.disable();
  ctx.cameraController = createCameraController(ctx.map);
  ctx.cameraController.bindInput();
  bindMapEventHandlers(ctx);
  mapContexts[workspaceId] = ctx;
  return ctx;
}

function storeMapContext(ctx) {
  if (!ctx) return;
  ctx.currentBasemap = currentBasemap;
  ctx.mapReady = mapReady;
  ctx.deckOverlay = deckOverlay;
  ctx.deckBuildingData = deckBuildingData;
  ctx.deckGroundData = deckGroundData;
  ctx.deckRefreshTimer = deckRefreshTimer;
  ctx.sunLight = sunLight;
  ctx.lightingEffect = lightingEffect;
  ctx.worldLayersRemoved = worldLayersRemoved;
  ctx.lastBoundaryFC = lastBoundaryFC;
  ctx.requestedBoundaryKey = requestedBoundaryKey;
}

function useMapContext(ctx) {
  activeMapContext = ctx;
  map = ctx.map;
  cameraController = ctx.cameraController;
  currentBasemap = ctx.currentBasemap;
  mapReady = ctx.mapReady;
  deckOverlay = ctx.deckOverlay;
  deckBuildingData = ctx.deckBuildingData;
  deckGroundData = ctx.deckGroundData;
  deckRefreshTimer = ctx.deckRefreshTimer;
  sunLight = ctx.sunLight;
  lightingEffect = ctx.lightingEffect;
  worldLayersRemoved = ctx.worldLayersRemoved;
  lastBoundaryFC = ctx.lastBoundaryFC;
  requestedBoundaryKey = ctx.requestedBoundaryKey;
}

function withMapContext(ctx, fn) {
  if (!ctx) return fn();
  var previous = activeMapContext;
  storeMapContext(previous);
  useMapContext(ctx);
  try {
    return fn();
  } finally {
    storeMapContext(ctx);
    if (previous && previous !== ctx) useMapContext(previous);
  }
}

function setActiveMapContainer(workspaceId) {
  var views = document.querySelectorAll('[data-map-workspace]');
  Array.prototype.forEach.call(views, function(view) {
    view.classList.toggle('active', view.dataset.mapWorkspace === workspaceId);
  });
}

function activateMapContext(workspaceId) {
  if (WORKSPACE_KINDS[workspaceId] === 'game') return false;
  storeMapContext(activeMapContext);
  setActiveMapContainer(workspaceId);
  useMapContext(mapContexts[workspaceId] || createMapContext(workspaceId));
  updateBasemapMenu();
  syncViewToggle();
  updateMapToolButtons();
  return true;
}

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
    bindViewToggleControls();
    syncViewToggle();
  }

  function syncViewToggle() {
    if (activeMapContext && activeMapContext.map !== mapInstance) return;
    var toggle = document.querySelector('#view-toggle .view-toggle-button');
    if (!toggle) return;
    var is3d = !isFlatView();
    toggle.textContent = is3d ? '3D' : '2D';
    toggle.classList.toggle('active', is3d);
    toggle.setAttribute('aria-pressed', is3d ? 'true' : 'false');
    toggle.setAttribute('aria-label', is3d ? '当前 3D，点击切换到 2D' : '当前 2D，点击切换到 3D');
    toggle.title = is3d ? '切换到 2D' : '切换到 3D';
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
    startCityOrbit: startCityOrbit,
    isFlatView: isFlatView,
    isCityOrbitActive: function() { return mode === MODES.CITY_ORBIT; }
  };
}

function bindViewToggleControls() {
  if (viewToggleBound) return;
  var toggle = document.querySelector('#view-toggle .view-toggle-button');
  if (!toggle) return;
  viewToggleBound = true;
  toggle.addEventListener('click', function() {
    if (!cameraController) return;
    if (cameraController.isFlatView()) cameraController.enter3DInPlace();
    else cameraController.exitTo2D();
  });
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
  var ctx = activeMapContext;
  if (!ctx) return;
  if (!force && (map.isMoving() || map.isZooming())) return;
  clearTimeout(deckRefreshTimer);
  deckRefreshTimer = setTimeout(function() {
    withMapContext(ctx, refreshDeckBuildings);
  }, 120);
  storeMapContext(ctx);
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

var worldGeojsonPromise = null;
var worldLayersRemoved = false;

function loadWorldGeojson() {
  if (!worldGeojsonPromise) {
    worldGeojsonPromise = fetch(WORLD_GEOJSON_URL)
      .then(function(r) { return r.json(); })
      .catch(function() { return null; });
  }
  return worldGeojsonPromise;
}

// 本地世界国界层：默认底图首帧即出「灰海 + 白陆 + 轮廓 + 国名」，
// 不必等 openfreemap 矢量瓦片。轮廓线无需字体，瞬间渲染；国名要等 glyphs
// （很小，远快于矢量瓦片）。等 openmaptiles 瓦片就绪后由 removeWorldBaseLayers
// 淡出移除，避免与瓦片自带的边界/标注重影。仅默认底图启用，卫星底图跳过。
function addWorldBaseLayers() {
  if (currentBasemap !== 'positron') return;
  var ctx = activeMapContext;
  worldLayersRemoved = false;
  loadWorldGeojson().then(function(data) {
    withMapContext(ctx, function() {
      if (!data || worldLayersRemoved || currentBasemap !== 'positron') return;
      if (map.getSource('world')) return;
      map.addSource('world-bg', { type: 'geojson', data: {
        type: 'Feature', properties: {},
        geometry: { type: 'Polygon', coordinates: [[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]] }
      } });
      map.addSource('world', { type: 'geojson', data: data });
      map.addLayer({
        id: 'world-ocean', type: 'fill', source: 'world-bg', maxzoom: 6,
        paint: { 'fill-color': WORLD_OCEAN_COLOR, 'fill-opacity': 1, 'fill-opacity-transition': { duration: 400 } }
      });
      map.addLayer({
        id: 'world-land', type: 'fill', source: 'world', maxzoom: 6,
        paint: { 'fill-color': WORLD_LAND_COLOR, 'fill-opacity': 1, 'fill-opacity-transition': { duration: 400 } }
      });
      map.addLayer({
        id: 'world-line', type: 'line', source: 'world', maxzoom: 6,
        paint: {
          'line-color': '#b9b4ad',
          'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0.4, 5, 1.2],
          'line-opacity': 1, 'line-opacity-transition': { duration: 400 }
        }
      });
      map.addLayer({
        id: 'world-label', type: 'symbol', source: 'world', maxzoom: 6,
        layout: {
          'text-field': ['coalesce', ['get', 'name'], ''],
          'text-font': ['Noto Sans Regular'],
          'text-size': ['interpolate', ['linear'], ['zoom'], 1, 10, 5, 15],
          'text-max-width': 7, 'text-padding': 4
        },
        paint: {
          'text-color': '#3c3c3c', 'text-halo-color': WORLD_LAND_COLOR, 'text-halo-width': 1.2,
          'text-opacity': 1, 'text-opacity-transition': { duration: 400 }
        }
      });
    });
  });
  storeMapContext(ctx);
}

function removeWorldBaseLayers() {
  var ctx = activeMapContext;
  if (worldLayersRemoved) return;
  worldLayersRemoved = true;
  if (!map.getSource('world')) return;
  [['world-ocean', 'fill-opacity'], ['world-land', 'fill-opacity'],
   ['world-line', 'line-opacity'], ['world-label', 'text-opacity']].forEach(function(pair) {
    if (!map.getLayer(pair[0])) return;
    try { map.setPaintProperty(pair[0], pair[1], 0); } catch (e) {}
  });
  setTimeout(function() {
    withMapContext(ctx, function() {
      ['world-ocean', 'world-land', 'world-line', 'world-label'].forEach(function(id) {
        if (map.getLayer(id)) { try { map.removeLayer(id); } catch (e) {} }
      });
      ['world', 'world-bg'].forEach(function(id) {
        if (map.getSource(id)) { try { map.removeSource(id); } catch (e) {} }
      });
    });
  }, 450);
  storeMapContext(ctx);
}

function setupMapLayers() {
  addWorldBaseLayers();
  setupDeckOverlay();
  map.addSource('grid', { type: 'geojson', data: emptyFeatureCollection() });
  map.addLayer({
    id: 'grid-fill',
    type: 'fill',
    source: 'grid',
    layout: { visibility: gridVisible ? 'visible' : 'none' },
    paint: {
      'fill-color': ['case', ['get', 'selected'], '#ffffff', ['get', 'cached'], '#3b82f6', '#ffffff'],
      'fill-opacity': ['case', ['get', 'selected'], ['case', ['get', 'cached'], 0.58, 0.54], ['get', 'cached'], 0.32, 0]
    }
  });
  map.addLayer({
    id: 'grid-line',
    type: 'line',
    source: 'grid',
    layout: { visibility: gridVisible ? 'visible' : 'none' },
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

function bindMapEventHandlers(ctx) {
  ctx.map.on('load', function() {
    withMapContext(ctx, function() {
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
        ctx.map.getContainer().classList.add('map-ready');
      });
    });
  });
  ctx.map.on('click', function(e) {
    if (activeMapContext !== ctx || !pointSelectActive) return;
    selectTileByLatLng(e.lngLat);
  });
  ctx.map.on('moveend', function() {
    if (activeMapContext !== ctx) return;
    scheduleGridLoad();
    if (cameraController && cameraController.isCityOrbitActive()) return;
    scheduleDeckRefresh(true);
  });
  ctx.map.on('zoomend', function() {
    if (activeMapContext !== ctx) return;
    scheduleGridLoad();
    scheduleDeckRefresh(true);
  });
  ctx.map.on('sourcedata', function(e) {
    if (e.sourceId !== 'openmaptiles' || !e.isSourceLoaded) return;
    withMapContext(ctx, function() {
      removeWorldBaseLayers();
      scheduleDeckRefresh();
    });
  });
}

function setBasemapStyle(id) {
  if (!mapReady) return;
  if (id === currentBasemap) {
    return;
  }
  var ctx = activeMapContext;
  var target = getBasemapStyle(id);
  map.once('styledata', function() {
    withMapContext(ctx, function() {
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
  });
  map.setStyle(target.style);
  currentBasemap = target.id;
  storeMapContext(ctx);
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
  var toggle = document.getElementById('basemap-toggle');
  if (!toggle) return;
  var current = getBasemapStyle(currentBasemap);
  var next = getNextBasemapStyle(currentBasemap);
  toggle.textContent = current.label;
  toggle.dataset.styleId = current.id;
  toggle.dataset.nextStyleId = next.id;
  toggle.setAttribute('aria-pressed', current.id === 'satellite' ? 'true' : 'false');
  toggle.setAttribute('aria-label', '当前底图：' + current.label + '，点击切换到' + next.label);
  toggle.title = '切换到' + next.label;
}

activateMapContext(activeWorkspaceId);
bindSelectionTools();

bindLocationSearch();
document.getElementById('houdini-path-input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    saveSoftwarePath(false);
  }
});
document.getElementById('houdini-path-input').addEventListener('blur', function() {
  saveSoftwarePath(false);
});

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
  var ctx = activeMapContext;
  if (!osmId) {
    hideBoundary();
    storeMapContext(ctx);
    return;
  }
  requestedBoundaryKey = String(osmId);
  var cached = boundaryCache[osmId];
  if (cached) {
    showBoundary(cached);
    storeMapContext(ctx);
    return;
  }
  fetch('/boundary?osm_type=R&osm_id=' + encodeURIComponent(osmId))
  .then(function(r) { return r.json(); })
  .then(function(d) {
    withMapContext(ctx, function() {
      if (requestedBoundaryKey !== String(osmId)) return;
      if (!d || !d.ok || !d.geojson) {
        hideBoundary();
        return;
      }
      var fc = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: d.geojson }] };
      boundaryCache[osmId] = fc;
      showBoundary(fc);
    });
  })
  .catch(function() {
    withMapContext(ctx, function() {
      if (requestedBoundaryKey !== String(osmId)) return;
      hideBoundary();
    });
  });
  storeMapContext(ctx);
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
  var host = document.getElementById('region-countries');
  var citiesHost = document.getElementById('region-cities');
  var sameCountryOpen = activeCountryId === country.id && citiesHost && !citiesHost.hidden;
  if (sameCountryOpen) {
    activeCountryId = null;
    if (host) {
      Array.prototype.forEach.call(host.children, function(node) {
        node.classList.remove('active');
      });
    }
    citiesHost.textContent = '';
    citiesHost.hidden = true;
    return;
  }
  activeCountryId = country.id;
  if (host) {
    Array.prototype.forEach.call(host.children, function(node) {
      node.classList.toggle('active', node === btn);
    });
  }
  loadBoundary(country.osmId);
  flyToBbox(country.bbox, 7);
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

window.addEventListener('resize', function() {
  if (WORKSPACE_KINDS[activeWorkspaceId] === 'game') return;
  if (!map) return;
  map.resize();
  if (activeWorkspaceId === 'houdini') scheduleGridLoad();
  if (typeof scheduleDeckRefresh === 'function') scheduleDeckRefresh(true);
});

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
