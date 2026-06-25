(function() {
  'use strict';

  var EARTH_RADIUS_KM = 6371;
  var ORBIT_TAIL_REBUILD_MS = 1600;
  var SOLAR_ORBIT_REBUILD_MS = 90000;
  var TWO_PI = Math.PI * 2;
  var DEFAULT_TIME_SCALE = 80;
  var SATELLITE_TRAJECTORY_MIN_STEP_MS = 12000;
  var SATELLITE_TRAJECTORY_MAX_STEP_MS = 120000;
  var SATELLITE_TRAJECTORY_MIN_FUTURE_MINUTES = 12;
  var SATELLITE_TRAJECTORY_MAX_FUTURE_MINUTES = 80;
  var SATELLITE_TRAJECTORY_FUTURE_FRACTION = 0.45;
  var J2000_MS = Date.UTC(2000, 0, 1, 12);
  var ORBIT_LINE_COLOR = [1, 1, 1, 0.96];
  var SOLAR_ORBIT_COLOR = [1, 1, 1, 0.30];
  var SUN_COLOR = [1.00, 0.93, 0.20, 0.96];
  var SOLAR_AU_TO_EARTH_RADIUS = 5.35;
  var SOLAR_GM_AU3_PER_DAY2 = 0.00029591220828559104;
  var SOLAR_PLANE_TILT = -18 * Math.PI / 180;
  var SOLAR_PLANE_YAW = -34 * Math.PI / 180;
  var PLANET_DEFS = [
    { id: 'mercury', label: '水星', au: 0.3871, periodDays: 87.969, meanLongitude: 252.251, inclination: 7.0, node: 48.3, size: 2.4, color: [0.70, 0.69, 0.64, 0.82], tailFraction: 0.64 },
    { id: 'venus', label: '金星', au: 0.7233, periodDays: 224.701, meanLongitude: 181.980, inclination: 3.4, node: 76.7, size: 3.2, color: [1.00, 0.82, 0.52, 0.86], tailFraction: 0.58 },
    { id: 'mars', label: '火星', au: 1.5237, periodDays: 686.980, meanLongitude: 355.453, inclination: 1.85, node: 49.6, size: 3.0, color: [1.00, 0.48, 0.36, 0.84], tailFraction: 0.50 },
    { id: 'jupiter', label: '木星', au: 5.2028, periodDays: 4332.589, meanLongitude: 34.404, inclination: 1.30, node: 100.5, size: 4.6, color: [1.00, 0.78, 0.48, 0.86], tailFraction: 0.34 },
    { id: 'saturn', label: '土星', au: 9.5388, periodDays: 10759.22, meanLongitude: 49.944, inclination: 2.49, node: 113.7, size: 4.1, color: [0.95, 0.82, 0.58, 0.80], tailFraction: 0.28 },
    { id: 'uranus', label: '天王星', au: 19.191, periodDays: 30685.4, meanLongitude: 313.232, inclination: 0.77, node: 74.0, size: 3.5, color: [0.58, 0.88, 1.00, 0.74], tailFraction: 0.22 },
    { id: 'neptune', label: '海王星', au: 30.061, periodDays: 60189.0, meanLongitude: 304.880, inclination: 1.77, node: 131.8, size: 3.4, color: [0.40, 0.58, 1.00, 0.72], tailFraction: 0.18 }
  ];

  function mount(map, options) {
    options = options || {};
    var satelliteApi = options.satellite || window.satellite;
    var feedUrl = options.feedUrl || '/orbit-tle?groups=stations,visual';
    var showPlanets = options.showPlanets === true;
    var planetFeedUrl = showPlanets ? (options.planetFeedUrl || '/planet-ephemeris') : '';
    var maxBodies = Math.max(1, Math.floor(options.maxBodies || 30));
    var requestedTimeScale = Number(options.timeScale || DEFAULT_TIME_SCALE);
    var timeScale = Number.isFinite(requestedTimeScale) && requestedTimeScale > 0 ? requestedTimeScale : DEFAULT_TIME_SCALE;
    var simulationRealStartMs = Date.now();
    var simulationStartMs = simulationRealStartMs;
    var orbitTailRebuildMs = Math.max(100, ORBIT_TAIL_REBUILD_MS / timeScale);
    if (!map || typeof map.getContainer !== 'function') return null;

    var host = map.getContainer();
    if (!host || host.querySelector('.space-preview-canvas')) return null;

    var glCanvas = document.createElement('canvas');
    glCanvas.className = 'space-preview-canvas';
    glCanvas.setAttribute('aria-hidden', 'true');
    host.appendChild(glCanvas);

    var labelCanvas = document.createElement('canvas');
    labelCanvas.className = 'space-label-canvas';
    labelCanvas.setAttribute('aria-hidden', 'true');
    host.appendChild(labelCanvas);

    var gl = glCanvas.getContext('webgl', {
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
      preserveDrawingBuffer: true
    });
    var labelCtx = labelCanvas.getContext('2d');
    if (!gl || !labelCtx) {
      removeCanvases();
      return null;
    }

    var dpr = 1;
    var width = 0;
    var height = 0;
    var sphereBuffer = gl.createBuffer();
    var pointBuffer = gl.createBuffer();
    var spaceBodies = [];
    var planetBodies = showPlanets ? createPlanetBodies() : [];
    var earthEphemeris = null;
    var solarReference = {
      builtAt: 0,
      scale: 0,
      earthKey: 0,
      planetOrbits: [],
      sunPoint: null
    };
    var animationFrame = 0;
    var destroyed = false;
    var orbitStatus = {
      loading: true,
      source: 'CelesTrak',
      message: 'loading live TLE data'
    };
    var planetStatus = showPlanets ? {
      loading: true,
      source: 'NASA/JPL Horizons',
      message: 'loading planet ephemeris'
    } : null;
    var stars = createStarfield(360);

    var fallbackTle = [
      'ISS (ZARYA)',
      '1 25544U 98067A   26167.86697329  .00007968  00000+0  15124-3 0  9997',
      '2 25544  51.6339 301.6783 0004749 194.3570 165.7284 15.49265361571705',
      'CSS (TIANHE)',
      '1 48274U 21035A   26167.84906358  .00020239  00000+0  23909-3 0  9992',
      '2 48274  41.4698 324.0596 0007460  74.3419 285.8242 15.60797895293117',
      'HST',
      '1 20580U 90037B   26167.82428788  .00004389  00000+0  19248-3 0  9998',
      '2 20580  28.4698 196.5277 0002416  78.7317 281.3539 15.17647408784864'
    ];

    function removeCanvases() {
      if (glCanvas.parentNode === host) host.removeChild(glCanvas);
      if (labelCanvas.parentNode === host) host.removeChild(labelCanvas);
    }

    function clamp(value, min, max) {
      return Math.max(min, Math.min(max, value));
    }

    function smoothstep(edge0, edge1, value) {
      var t = clamp((value - edge0) / (edge1 - edge0), 0, 1);
      return t * t * (3 - 2 * t);
    }

    function simulationDate(realNowMs) {
      var nowMs = Number.isFinite(realNowMs) ? realNowMs : Date.now();
      return new Date(simulationStartMs + (nowMs - simulationRealStartMs) * timeScale);
    }

    function compileShader(type, source) {
      var shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error(gl.getShaderInfoLog(shader));
        return null;
      }
      return shader;
    }

    function createProgram(vertexSource, fragmentSource) {
      var vertex = compileShader(gl.VERTEX_SHADER, vertexSource);
      var fragment = compileShader(gl.FRAGMENT_SHADER, fragmentSource);
      if (!vertex || !fragment) return null;
      var program = gl.createProgram();
      gl.attachShader(program, vertex);
      gl.attachShader(program, fragment);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        console.error(gl.getProgramInfoLog(program));
        return null;
      }
      return program;
    }

    var sharedVertex =
      'attribute vec3 a_position;\n' +
      'uniform vec2 u_resolution;\n' +
      'uniform vec2 u_center;\n' +
      'uniform float u_scale;\n' +
      'uniform float u_cameraDistance;\n' +
      'uniform float u_depthScale;\n' +
      'uniform float u_pitchSin;\n' +
      'uniform float u_pitchCos;\n' +
      'uniform float u_pointSize;\n' +
      'uniform mat3 u_sceneRotation;\n' +
      'varying float v_alpha;\n' +
      'float saturate(float v){ return clamp(v, 0.0, 1.0); }\n' +
      'void main(){\n' +
      '  vec3 base = u_sceneRotation * a_position;\n' +
      '  vec3 p = vec3(base.x, base.y * u_pitchCos - (base.z - 1.0) * u_pitchSin, 1.0 + base.y * u_pitchSin + (base.z - 1.0) * u_pitchCos);\n' +
      '  float distance = max(0.22, u_cameraDistance - p.z * 0.56);\n' +
      '  float perspective = clamp(u_cameraDistance / distance, 0.55, 2.85);\n' +
      '  vec2 screen = u_center + vec2(p.x, -p.y) * u_scale * perspective;\n' +
      '  vec2 clip = vec2(screen.x / u_resolution.x * 2.0 - 1.0, 1.0 - screen.y / u_resolution.y * 2.0);\n' +
      '  gl_Position = vec4(clip, clamp(-p.z * u_depthScale, -0.96, 0.96), 1.0);\n' +
      '  gl_PointSize = u_pointSize * clamp(perspective, 0.72, 1.85);\n' +
      '  v_alpha = smoothstep(-0.22, 0.72, p.z) * saturate(perspective * 0.92);\n' +
      '}\n';

    var lineProgram = createProgram(
      sharedVertex,
      'precision mediump float;\n' +
      'uniform vec4 u_color;\n' +
      'varying float v_alpha;\n' +
      'void main(){ gl_FragColor = vec4(u_color.rgb, u_color.a * v_alpha); }\n'
    );

    var pointProgram = createProgram(
      sharedVertex,
      'precision mediump float;\n' +
      'uniform vec4 u_color;\n' +
      'varying float v_alpha;\n' +
      'void main(){\n' +
      '  vec2 d = gl_PointCoord - vec2(0.5);\n' +
      '  float r = length(d);\n' +
      '  if (r > 0.5) discard;\n' +
      '  float core = smoothstep(0.5, 0.12, r);\n' +
      '  float halo = smoothstep(0.5, 0.30, r) * 0.55;\n' +
      '  gl_FragColor = vec4(u_color.rgb, u_color.a * v_alpha * max(core, halo));\n' +
      '}\n'
    );

    if (!lineProgram || !pointProgram) {
      removeCanvases();
      return null;
    }

    function programInfo(program) {
      return {
        program: program,
        position: gl.getAttribLocation(program, 'a_position'),
        resolution: gl.getUniformLocation(program, 'u_resolution'),
        center: gl.getUniformLocation(program, 'u_center'),
        scale: gl.getUniformLocation(program, 'u_scale'),
        cameraDistance: gl.getUniformLocation(program, 'u_cameraDistance'),
        depthScale: gl.getUniformLocation(program, 'u_depthScale'),
        pitchSin: gl.getUniformLocation(program, 'u_pitchSin'),
        pitchCos: gl.getUniformLocation(program, 'u_pitchCos'),
        sceneRotation: gl.getUniformLocation(program, 'u_sceneRotation'),
        color: gl.getUniformLocation(program, 'u_color'),
        pointSize: gl.getUniformLocation(program, 'u_pointSize')
      };
    }

    var lineInfo = programInfo(lineProgram);
    var pointInfo = programInfo(pointProgram);

    function useProgram(info, geom, color) {
      gl.useProgram(info.program);
      gl.uniform2f(info.resolution, width * dpr, height * dpr);
      gl.uniform2f(info.center, geom.x * dpr, geom.y * dpr);
      gl.uniform1f(info.scale, geom.r * dpr);
      gl.uniform1f(info.cameraDistance, geom.cameraDistance);
      gl.uniform1f(info.depthScale, 0.15);
      gl.uniform1f(info.pitchSin, geom.pitchSin);
      gl.uniform1f(info.pitchCos, geom.pitchCos);
      gl.uniformMatrix3fv(info.sceneRotation, false, geom.matrix);
      gl.uniform4f(info.color, color[0], color[1], color[2], color[3]);
      if (info.pointSize) gl.uniform1f(info.pointSize, 1);
    }

    function setPositionAttribute(info, buffer) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.enableVertexAttribArray(info.position);
      gl.vertexAttribPointer(info.position, 3, gl.FLOAT, false, 0, 0);
    }

    function vecDot(a, b) {
      return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    }

    function vecNormalize(v) {
      var length = Math.hypot(v[0], v[1], v[2]) || 1;
      return [v[0] / length, v[1] / length, v[2] / length];
    }

    function vecCross(a, b) {
      return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0]
      ];
    }

    function vecScale(v, scale) {
      return [v[0] * scale, v[1] * scale, v[2] * scale];
    }

    function vecAdd(a, b) {
      return [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
    }

    function vecSub(a, b) {
      return [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    }

    function vectorFromLngLat(lngDeg, latDeg, radius) {
      var lng = lngDeg * Math.PI / 180;
      var lat = latDeg * Math.PI / 180;
      var cosLat = Math.cos(lat);
      return [
        radius * cosLat * Math.sin(lng),
        radius * Math.sin(lat),
        radius * cosLat * Math.cos(lng)
      ];
    }

    function viewMatrixForCenter(center) {
      var lng = center.lng * Math.PI / 180;
      var lat = clamp(center.lat, -84, 84) * Math.PI / 180;
      var up = vectorFromLngLat(center.lng, center.lat, 1);
      var east = vecNormalize([Math.cos(lng), 0, -Math.sin(lng)]);
      var north = vecNormalize([
        -Math.sin(lat) * Math.sin(lng),
        Math.cos(lat),
        -Math.sin(lat) * Math.cos(lng)
      ]);
      var bearing = -map.getBearing() * Math.PI / 180;
      var cb = Math.cos(bearing);
      var sb = Math.sin(bearing);
      var rowX = [
        east[0] * cb - north[0] * sb,
        east[1] * cb - north[1] * sb,
        east[2] * cb - north[2] * sb
      ];
      var rowY = [
        east[0] * sb + north[0] * cb,
        east[1] * sb + north[1] * cb,
        east[2] * sb + north[2] * cb
      ];
      var rowZ = up;
      return [
        rowX[0], rowY[0], rowZ[0],
        rowX[1], rowY[1], rowZ[1],
        rowX[2], rowY[2], rowZ[2]
      ];
    }

    function transformPoint(matrix, point) {
      return [
        matrix[0] * point[0] + matrix[3] * point[1] + matrix[6] * point[2],
        matrix[1] * point[0] + matrix[4] * point[1] + matrix[7] * point[2],
        matrix[2] * point[0] + matrix[5] * point[1] + matrix[8] * point[2]
      ];
    }

    function applyPitch(geom, point) {
      return [
        point[0],
        point[1] * geom.pitchCos - (point[2] - 1) * geom.pitchSin,
        1 + point[1] * geom.pitchSin + (point[2] - 1) * geom.pitchCos
      ];
    }

    function rotateForView(geom, point) {
      return applyPitch(geom, transformPoint(geom.matrix, point));
    }

    function projectWorldPoint(geom, point) {
      var view = rotateForView(geom, point);
      var distance = Math.max(0.22, geom.cameraDistance - view[2] * 0.56);
      var perspective = clamp(geom.cameraDistance / distance, 0.55, 2.85);
      return {
        x: geom.x + view[0] * geom.r * perspective,
        y: geom.y - view[1] * geom.r * perspective,
        z: view[2],
        perspective: perspective,
        view: view
      };
    }

    function projectSolarPoint(geom, point) {
      var view = rotateForView(geom, point);
      var perspective = 1;
      return {
        x: geom.x + view[0] * geom.r,
        y: geom.y - view[1] * geom.r,
        z: view[2],
        perspective: perspective,
        view: view
      };
    }

    function eciPositionToWorld(positionEci, gmst) {
      if (!positionEci || !Number.isFinite(positionEci.x) || !Number.isFinite(positionEci.y) || !Number.isFinite(positionEci.z)) {
        return null;
      }
      var geodetic = satelliteApi.eciToGeodetic(positionEci, gmst);
      var lat = satelliteApi.degreesLat(geodetic.latitude);
      var lng = satelliteApi.degreesLong(geodetic.longitude);
      var earthRadii = 1 + clamp((geodetic.height || 0) / EARTH_RADIUS_KM, 0.035, 8);
      return vectorFromLngLat(lng, lat, earthRadii);
    }

    function directSampleSatelliteWorld(body, date) {
      if (!body || !body.satrec || !satelliteApi) return null;
      var state = satelliteApi.propagate(body.satrec, date);
      if (!state || !state.position) return null;
      return eciPositionToWorld(state.position, satelliteApi.gstime(date));
    }

    function directSampleSatelliteFrame(body, date) {
      var position = directSampleSatelliteWorld(body, date);
      if (!position) return null;
      var probeMs = 1000;
      var before = directSampleSatelliteWorld(body, new Date(date.getTime() - probeMs));
      var after = directSampleSatelliteWorld(body, new Date(date.getTime() + probeMs));
      var spanSeconds = 0;
      var velocity = [0, 0, 0];
      if (before && after) {
        spanSeconds = probeMs * 2 / 1000;
        velocity = [
          (after[0] - before[0]) / spanSeconds,
          (after[1] - before[1]) / spanSeconds,
          (after[2] - before[2]) / spanSeconds
        ];
      } else if (after) {
        spanSeconds = probeMs / 1000;
        velocity = [
          (after[0] - position[0]) / spanSeconds,
          (after[1] - position[1]) / spanSeconds,
          (after[2] - position[2]) / spanSeconds
        ];
      }
      return { position: position, velocity: velocity };
    }

    function deriveTrajectoryVelocities(frames) {
      if (!frames || frames.length < 2) return;
      for (var i = 0; i < frames.length; i++) {
        var previous = frames[Math.max(0, i - 1)];
        var next = frames[Math.min(frames.length - 1, i + 1)];
        var spanSeconds = Math.max(0.001, (next.time - previous.time) / 1000);
        frames[i].velocity = [
          (next.position[0] - previous.position[0]) / spanSeconds,
          (next.position[1] - previous.position[1]) / spanSeconds,
          (next.position[2] - previous.position[2]) / spanSeconds
        ];
      }
    }

    function hermiteTrajectoryFrame(a, b, timeMs) {
      var spanSeconds = Math.max(0.001, (b.time - a.time) / 1000);
      var f = clamp((timeMs - a.time) / (b.time - a.time || 1), 0, 1);
      var f2 = f * f;
      var f3 = f2 * f;
      var h00 = 2 * f3 - 3 * f2 + 1;
      var h10 = f3 - 2 * f2 + f;
      var h01 = -2 * f3 + 3 * f2;
      var h11 = f3 - f2;
      var dh00 = 6 * f2 - 6 * f;
      var dh10 = 3 * f2 - 4 * f + 1;
      var dh01 = -6 * f2 + 6 * f;
      var dh11 = 3 * f2 - 2 * f;
      var av = a.velocity || [0, 0, 0];
      var bv = b.velocity || [0, 0, 0];
      var position = [];
      var velocity = [];
      for (var i = 0; i < 3; i++) {
        var m0 = av[i] * spanSeconds;
        var m1 = bv[i] * spanSeconds;
        position[i] = h00 * a.position[i] + h10 * m0 + h01 * b.position[i] + h11 * m1;
        velocity[i] = (dh00 * a.position[i] + dh10 * m0 + dh01 * b.position[i] + dh11 * m1) / spanSeconds;
      }
      return { position: position, velocity: velocity };
    }

    function interpolateTrajectoryAt(body, timeMs) {
      var frames = body && body.trajectoryFrames;
      if (!frames || frames.length < 2) return null;
      if (timeMs <= frames[0].time) {
        return {
          position: frames[0].position.slice(),
          velocity: (frames[0].velocity || [0, 0, 0]).slice()
        };
      }
      var last = frames[frames.length - 1];
      if (timeMs >= last.time) {
        return {
          position: last.position.slice(),
          velocity: (last.velocity || [0, 0, 0]).slice()
        };
      }
      var lo = 0;
      var hi = frames.length - 2;
      while (lo < hi) {
        var mid = Math.ceil((lo + hi) / 2);
        if (timeMs < frames[mid].time) hi = mid - 1;
        else lo = mid;
      }
      return hermiteTrajectoryFrame(frames[lo], frames[lo + 1], timeMs);
    }

    function buildTrajectoryCache(body, centerDate) {
      if (!body || !body.satrec || !centerDate) return false;
      var periodMinutes = body.periodMinutes || 96;
      var tailMinutes = periodMinutes * (body.tailFraction || 0.72);
      var futureMinutes = clamp(
        periodMinutes * SATELLITE_TRAJECTORY_FUTURE_FRACTION,
        SATELLITE_TRAJECTORY_MIN_FUTURE_MINUTES,
        SATELLITE_TRAJECTORY_MAX_FUTURE_MINUTES
      );
      var sampleCount = Math.max(12, body.samples || 190);
      var stepMs = clamp(
        tailMinutes * 60000 / sampleCount,
        SATELLITE_TRAJECTORY_MIN_STEP_MS,
        SATELLITE_TRAJECTORY_MAX_STEP_MS
      );
      var centerMs = centerDate.getTime();
      var startMs = centerMs - tailMinutes * 60000;
      var endMs = centerMs + futureMinutes * 60000;
      var frames = [];
      for (var t = startMs; t <= endMs + stepMs * 0.5; t += stepMs) {
        var position = directSampleSatelliteWorld(body, new Date(t));
        if (!position) continue;
        frames.push({ time: t, position: position });
      }
      if (frames.length < 2) return false;
      deriveTrajectoryVelocities(frames);
      body.trajectoryFrames = frames;
      body.trajectoryStartMs = frames[0].time;
      body.trajectoryEndMs = frames[frames.length - 1].time;
      body.trajectoryStepMs = stepMs;
      body.trajectoryTailMinutes = tailMinutes;
      body.trajectoryBuiltRealAt = Date.now();
      return true;
    }

    function ensureTrajectoryCache(body, date) {
      if (!body || !date) return false;
      var timeMs = date.getTime();
      var frames = body.trajectoryFrames;
      if (!frames || frames.length < 2) return buildTrajectoryCache(body, date);
      var edge = Math.max(body.trajectoryStepMs || SATELLITE_TRAJECTORY_MIN_STEP_MS, 1) * 3;
      if (timeMs < body.trajectoryStartMs + edge || timeMs > body.trajectoryEndMs - edge) {
        return buildTrajectoryCache(body, date);
      }
      return true;
    }

    function sampleSatelliteFrame(body, date) {
      if (!ensureTrajectoryCache(body, date)) {
        return directSampleSatelliteFrame(body, date);
      }
      return interpolateTrajectoryAt(body, date.getTime());
    }

    function sampleSatelliteWorld(body, date) {
      var frame = sampleSatelliteFrame(body, date);
      return frame ? frame.position : null;
    }

    function createPlanetBodies() {
      return PLANET_DEFS.map(function(def, index) {
        return {
          id: def.id,
          label: def.label,
          def: def,
          color: def.color,
          size: def.size,
          showLabel: index < 5,
          highlight: index < 3 ? 0.88 : 0.58
        };
      });
    }

    function planetDefById(id) {
      for (var i = 0; i < PLANET_DEFS.length; i++) {
        if (PLANET_DEFS[i].id === id) return PLANET_DEFS[i];
      }
      return null;
    }

    function rotateSolarPlane(point) {
      var yawC = Math.cos(SOLAR_PLANE_YAW);
      var yawS = Math.sin(SOLAR_PLANE_YAW);
      var tiltC = Math.cos(SOLAR_PLANE_TILT);
      var tiltS = Math.sin(SOLAR_PLANE_TILT);
      var x1 = point[0] * yawC - point[2] * yawS;
      var z1 = point[0] * yawS + point[2] * yawC;
      var y2 = point[1] * tiltC - z1 * tiltS;
      var z2 = point[1] * tiltS + z1 * tiltC;
      return [x1, y2, z2];
    }

    function heliocentricPosition(def, date) {
      var days = (date.getTime() - J2000_MS) / 86400000;
      var mean = ((def.meanLongitude + days / def.periodDays * 360) % 360) * Math.PI / 180;
      var inclination = def.inclination * Math.PI / 180;
      var node = def.node * Math.PI / 180;
      var orbitalX = Math.cos(mean) * def.au;
      var orbitalY = Math.sin(mean) * def.au;
      var cosNode = Math.cos(node);
      var sinNode = Math.sin(node);
      var cosInc = Math.cos(inclination);
      var sinInc = Math.sin(inclination);
      return [
        orbitalX * cosNode - orbitalY * cosInc * sinNode,
        orbitalX * sinNode + orbitalY * cosInc * cosNode,
        orbitalY * sinInc
      ];
    }

    function earthHeliocentricPosition(date) {
      return heliocentricPosition({ au: 1, periodDays: 365.256, meanLongitude: 100.464, inclination: 0, node: 0 }, date);
    }

    function julianDate(date) {
      return date.getTime() / 86400000 + 2440587.5;
    }

    function interpolateVector(vectors, date) {
      if (!vectors || !vectors.length) return null;
      var jd = julianDate(date);
      if (jd <= vectors[0].jd) return vectors[0];
      var last = vectors[vectors.length - 1];
      if (jd >= last.jd) return last;
      for (var i = 1; i < vectors.length; i++) {
        var current = vectors[i];
        if (jd > current.jd) continue;
        var previous = vectors[i - 1];
        var span = current.jd - previous.jd || 1;
        var t = clamp((jd - previous.jd) / span, 0, 1);
        return {
          jd: jd,
          x: previous.x + (current.x - previous.x) * t,
          y: previous.y + (current.y - previous.y) * t,
          z: previous.z + (current.z - previous.z) * t,
          vx: Number.isFinite(previous.vx) && Number.isFinite(current.vx) ? previous.vx + (current.vx - previous.vx) * t : null,
          vy: Number.isFinite(previous.vy) && Number.isFinite(current.vy) ? previous.vy + (current.vy - previous.vy) * t : null,
          vz: Number.isFinite(previous.vz) && Number.isFinite(current.vz) ? previous.vz + (current.vz - previous.vz) * t : null
        };
      }
      return last;
    }

    function vectorToArray(vector) {
      if (!vector) return null;
      var x = Number(vector.x);
      var y = Number(vector.y);
      var z = Number(vector.z);
      if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
      return [x, y, z];
    }

    function velocityToArray(vector) {
      if (!vector) return null;
      var vx = Number(vector.vx);
      var vy = Number(vector.vy);
      var vz = Number(vector.vz);
      if (!Number.isFinite(vx) || !Number.isFinite(vy) || !Number.isFinite(vz)) return null;
      return [vx, vy, vz];
    }

    function solarVector(body, date) {
      if (body && body.vectors && body.vectors.length) {
        return vectorToArray(interpolateVector(body.vectors, date));
      }
      if (body && body.def) return heliocentricPosition(body.def, date);
      return null;
    }

    function earthSolarVector(date) {
      if (earthEphemeris && earthEphemeris.vectors && earthEphemeris.vectors.length) {
        var vector = vectorToArray(interpolateVector(earthEphemeris.vectors, date));
        if (vector) return vector;
      }
      return earthHeliocentricPosition(date);
    }

    function solarSystemScale(date) {
      return SOLAR_AU_TO_EARTH_RADIUS;
    }

    function solarScenePoint(vector, earthNow, scale) {
      if (!vector || !earthNow) return null;
      var sx = vector[0] - earthNow[0];
      var sy = vector[1] - earthNow[1];
      var sz = vector[2] - earthNow[2];
      return rotateSolarPlane([sx * scale, sz * scale, sy * scale]);
    }

    function samplePlanetWorld(body, date, scale) {
      return solarScenePoint(solarVector(body, date), earthSolarVector(date), scale);
    }

    function sampleSolarSceneAt(body, date, earthNow, scale) {
      return solarScenePoint(solarVector(body, date), earthNow, scale);
    }

    function sampleApproximateOrbitSceneAt(body, date, earthNow, scale) {
      if (!body || !body.def) return null;
      return solarScenePoint(heliocentricPosition(body.def, date), earthNow, scale);
    }

    function osculatingOrbitPoints(body, date, earthNow, scale) {
      var state = body && body.vectors ? interpolateVector(body.vectors, date) : null;
      var r = vectorToArray(state);
      var v = velocityToArray(state);
      if (!r || !v) return null;
      var radius = Math.hypot(r[0], r[1], r[2]);
      var speed2 = vecDot(v, v);
      if (radius <= 0 || speed2 <= 0) return null;
      var h = vecCross(r, v);
      var hMag = Math.hypot(h[0], h[1], h[2]);
      if (hMag <= 0) return null;
      var eccentricityVector = vecSub(vecScale(vecCross(v, h), 1 / SOLAR_GM_AU3_PER_DAY2), vecScale(r, 1 / radius));
      var eccentricity = Math.hypot(eccentricityVector[0], eccentricityVector[1], eccentricityVector[2]);
      var semiMajor = 1 / (2 / radius - speed2 / SOLAR_GM_AU3_PER_DAY2);
      if (!Number.isFinite(semiMajor) || semiMajor <= 0 || eccentricity >= 0.98) return null;
      var p = semiMajor * (1 - eccentricity * eccentricity);
      var periAxis = eccentricity > 0.0001 ? vecScale(eccentricityVector, 1 / eccentricity) : vecNormalize(r);
      var normal = vecScale(h, 1 / hMag);
      var sideAxis = vecNormalize(vecCross(normal, periAxis));
      var currentAnomaly = Math.atan2(vecDot(sideAxis, r) / radius, vecDot(periAxis, r) / radius);
      var samples = Math.min(540, Math.max(220, Math.round(body.def.periodDays / 2)));
      var data = [];
      for (var i = 0; i <= samples; i++) {
        var anomaly = currentAnomaly + TWO_PI * i / samples;
        var denom = 1 + eccentricity * Math.cos(anomaly);
        if (Math.abs(denom) < 0.0001) continue;
        var orbitalRadius = p / denom;
        var vector = (i === 0 || i === samples)
          ? r
          : vecAdd(vecScale(periAxis, Math.cos(anomaly) * orbitalRadius), vecScale(sideAxis, Math.sin(anomaly) * orbitalRadius));
        var point = solarScenePoint(vector, earthNow, scale);
        if (point) data.push(point[0], point[1], point[2]);
      }
      return data.length >= 6 ? data : null;
    }

    function sampleSunWorld(earthNow, scale) {
      return solarScenePoint([0, 0, 0], earthNow, scale);
    }

    function buildSolarReference(nowDate, scale) {
      var earthNow = earthSolarVector(nowDate);
      var planetOrbits = [];
      planetBodies.forEach(function(body) {
        var data = osculatingOrbitPoints(body, nowDate, earthNow, scale);
        if (!data) {
          var samples = Math.min(420, Math.max(180, Math.round(body.def.periodDays / 2)));
          var spanDays = body.def.periodDays;
          data = [];
          for (var i = 0; i <= samples; i++) {
            var offsetDays = spanDays * i / samples;
            var fallbackDate = new Date(nowDate.getTime() + offsetDays * 86400000);
            var p = sampleApproximateOrbitSceneAt(body, fallbackDate, earthNow, scale);
            if (p) data.push(p[0], p[1], p[2]);
          }
        }
        if (data.length >= 6) planetOrbits.push({ body: body, points: data });
      });
      solarReference = {
        builtAt: nowDate.getTime(),
        scale: scale,
        earthKey: earthNow.map(function(value) { return value.toFixed(4); }).join(','),
        planetOrbits: planetOrbits,
        sunPoint: sampleSunWorld(earthNow, scale)
      };
      return solarReference;
    }

    function getSolarReference(nowDate, scale) {
      var earthNow = earthSolarVector(nowDate);
      var earthKey = earthNow.map(function(value) { return value.toFixed(4); }).join(',');
      if (
        !solarReference ||
        !solarReference.builtAt ||
        Math.abs(nowDate.getTime() - solarReference.builtAt) > SOLAR_ORBIT_REBUILD_MS ||
        !Number.isFinite(solarReference.scale) ||
        Math.abs(solarReference.scale - scale) > 0.002 ||
        solarReference.earthKey !== earthKey
      ) {
        return buildSolarReference(nowDate, scale);
      }
      return solarReference;
    }

    function buildOrbitTail(body, startDate) {
      if (!body || !body.satrec) return false;
      if (!ensureTrajectoryCache(body, startDate)) return false;
      var tailMinutes = body.trajectoryTailMinutes || (body.periodMinutes || 96) * (body.tailFraction || 0.72);
      var startMs = startDate.getTime();
      var samples = Math.max(12, body.samples || 190);
      var stepMs = tailMinutes * 60000 / samples;
      var data = [];
      for (var i = 0; i <= samples; i++) {
        var frame = interpolateTrajectoryAt(body, startMs - i * stepMs);
        if (!frame || !frame.position) continue;
        data.push(frame.position[0], frame.position[1], frame.position[2]);
      }
      if (data.length < 6) return false;
      body.trailPoints = data;
      body.trailBuiltAt = startDate.getTime();
      body.trailBuiltRealAt = Date.now();
      return true;
    }

    function pushSpherePoint(data, theta, phi) {
      data.push(Math.sin(theta) * Math.cos(phi), Math.cos(theta), Math.sin(theta) * Math.sin(phi));
    }

    function buildSphereBuffer() {
      var latSteps = 34;
      var lonSteps = 68;
      var data = [];
      for (var lat = 0; lat < latSteps; lat++) {
        var t0 = lat / latSteps * Math.PI;
        var t1 = (lat + 1) / latSteps * Math.PI;
        for (var lon = 0; lon < lonSteps; lon++) {
          var p0 = lon / lonSteps * TWO_PI;
          var p1 = (lon + 1) / lonSteps * TWO_PI;
          pushSpherePoint(data, t0, p0);
          pushSpherePoint(data, t1, p0);
          pushSpherePoint(data, t1, p1);
          pushSpherePoint(data, t0, p0);
          pushSpherePoint(data, t1, p1);
          pushSpherePoint(data, t0, p1);
        }
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, sphereBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
      return data.length / 3;
    }

    var sphereVertexCount = buildSphereBuffer();

    function parseTleTriples(text) {
      var lines = String(text || '').split(/\r?\n/).map(function(line) {
        return line.trim();
      }).filter(Boolean);
      var triples = [];
      for (var i = 0; i < lines.length - 2; i++) {
        if (lines[i + 1].charAt(0) === '1' && lines[i + 2].charAt(0) === '2') {
          triples.push({ name: lines[i], line1: lines[i + 1], line2: lines[i + 2] });
          i += 2;
        }
      }
      return triples;
    }

    function tleCatalogKey(item) {
      var catalog = item && item.line1 ? item.line1.slice(2, 7).trim() : '';
      return catalog || (item.name + '|' + item.line1 + '|' + item.line2);
    }

    function satelliteColor(index, name) {
      if (/ISS|ZARYA/i.test(name)) return [1.00, 1.00, 1.00, 0.92];
      if (/CSS|TIANHE|WENTIAN|MENGTIAN/i.test(name)) return [1.00, 0.74, 0.42, 0.88];
      if (/HST|HUBBLE/i.test(name)) return [0.68, 0.84, 1.00, 0.86];
      if (/TDRS|GOES|GEO/i.test(name)) return [1.00, 0.84, 0.54, 0.66];
      var palette = [
        [0.62, 0.77, 1.00, 0.72],
        [0.42, 0.66, 1.00, 0.70],
        [0.82, 0.93, 1.00, 0.68],
        [0.58, 0.95, 0.86, 0.66],
        [1.00, 0.82, 0.48, 0.66]
      ];
      return palette[index % palette.length];
    }

    function tleToBody(item, index) {
      if (!satelliteApi || !satelliteApi.twoline2satrec) return null;
      try {
        var satrec = satelliteApi.twoline2satrec(item.line1, item.line2);
        if (!satrec || satrec.error) return null;
        var meanMotionRevPerDay = parseFloat(item.line2.slice(52, 63));
        var periodMinutes = Number.isFinite(meanMotionRevPerDay) && meanMotionRevPerDay > 0 ? 1440 / meanMotionRevPerDay : 96;
        var name = item.name.replace(/\s+/g, ' ').trim();
        var isFeatured = /ISS|CSS|TIANHE|HST|HUBBLE/i.test(name);
        var isSlow = periodMinutes > 400;
        return {
          label: name.length > 20 ? name.slice(0, 20).trim() : name,
          fullLabel: name,
          satrec: satrec,
          periodMinutes: periodMinutes,
          samples: isSlow ? 260 : 190,
          tailFraction: isSlow ? 0.42 : 0.76,
          size: isFeatured ? 5.4 : 3.6,
          color: satelliteColor(index, name),
          showLabel: isFeatured || index < 8,
          highlight: isFeatured ? 1 : 0.55,
          index: index
        };
      } catch (e) {
        return null;
      }
    }

    function applyTleData(text, options) {
      var triples = parseTleTriples(text);
      var preferred = [];
      var others = [];
      var seenCatalog = {};
      triples.forEach(function(item) {
        var key = tleCatalogKey(item);
        if (seenCatalog[key]) return;
        seenCatalog[key] = true;
        if (/ISS \(ZARYA\)|CSS \(TIANHE\)|CSS \(WENTIAN\)|CSS \(MENGTIAN\)|HST|HUBBLE/i.test(item.name)) preferred.push(item);
        else others.push(item);
      });
      var selected = preferred.concat(others).slice(0, maxBodies);
      var nextBodies = [];
      var now = simulationDate();
      selected.forEach(function(item, index) {
        var body = tleToBody(item, index);
        if (!body) return;
        if (buildOrbitTail(body, now)) nextBodies.push(body);
      });
      if (!nextBodies.length) return false;
      spaceBodies = nextBodies;
      orbitStatus = {
        loading: false,
        source: options && options.source ? options.source : 'CelesTrak',
        message: (options && options.cached ? 'cached ' : 'live ') + spaceBodies.length + ' satellites'
      };
      return true;
    }

    function applyPlanetEphemeris(payload) {
      if (!payload || !Array.isArray(payload.planets) || !payload.planets.length) return false;
      var nextEarth = null;
      if (payload.earth && Array.isArray(payload.earth.vectors) && payload.earth.vectors.length) {
        nextEarth = {
          id: 'earth',
          label: payload.earth.label || '地球',
          vectors: payload.earth.vectors.map(function(row) {
            return {
              jd: Number(row.jd),
              x: Number(row.x),
              y: Number(row.y),
              z: Number(row.z),
              vx: Number(row.vx),
              vy: Number(row.vy),
              vz: Number(row.vz)
            };
          }).filter(function(row) {
            return Number.isFinite(row.jd) && Number.isFinite(row.x) && Number.isFinite(row.y) && Number.isFinite(row.z);
          })
        };
      }
      if (!nextEarth || !nextEarth.vectors.length) return false;
      var byId = {};
      payload.planets.forEach(function(item) {
        if (!item || !item.id || !Array.isArray(item.vectors) || !item.vectors.length) return;
        byId[item.id] = item;
      });
      var nextPlanets = [];
      PLANET_DEFS.forEach(function(def, index) {
        var item = byId[def.id];
        var body = {
          id: def.id,
          label: item && item.label ? item.label : def.label,
          def: def,
          color: def.color,
          size: def.size,
          showLabel: index < 5,
          highlight: index < 3 ? 0.88 : 0.58,
          vectors: item ? item.vectors.map(function(row) {
            return {
              jd: Number(row.jd),
              x: Number(row.x),
              y: Number(row.y),
              z: Number(row.z),
              vx: Number(row.vx),
              vy: Number(row.vy),
              vz: Number(row.vz)
            };
          }).filter(function(row) {
            return Number.isFinite(row.jd) && Number.isFinite(row.x) && Number.isFinite(row.y) && Number.isFinite(row.z);
          }) : null
        };
        if (body.vectors && body.vectors.length) nextPlanets.push(body);
      });
      if (!nextPlanets.length) return false;
      earthEphemeris = nextEarth;
      planetBodies = nextPlanets;
      solarReference.builtAt = 0;
      planetStatus = {
        loading: false,
        source: payload.source || 'NASA/JPL Horizons',
        message: (payload.cached ? 'cached ' : 'live ') + planetBodies.length + ' heliocentric orbits'
      };
      return true;
    }

    function loadOrbitData() {
      if (!satelliteApi) {
        orbitStatus = {
          loading: false,
          source: 'orbit preview',
          message: 'satellite.js unavailable'
        };
        return;
      }
      applyTleData(fallbackTle.join('\n'), { source: 'fallback TLE', cached: true });
      fetch(feedUrl, { cache: 'no-store' })
        .then(function(resp) {
          if (!resp.ok) throw new Error('orbit feed HTTP ' + resp.status);
          return resp.json();
        })
        .then(function(payload) {
          if (!payload || !payload.ok || !payload.tle) throw new Error((payload && payload.errors || []).join('; ') || 'empty orbit feed');
          if (!applyTleData(payload.tle, { source: payload.source || 'CelesTrak', cached: !!payload.cached })) {
            throw new Error('no valid satellites in orbit feed');
          }
        })
        .catch(function(err) {
          console.warn('Orbit feed unavailable, keeping fallback TLE.', err);
          if (!spaceBodies.length) {
            applyTleData(fallbackTle.join('\n'), { source: 'fallback TLE', cached: true });
          }
        });
    }

    loadOrbitData();

    function loadPlanetData() {
      fetch(planetFeedUrl, { cache: 'no-store' })
        .then(function(resp) {
          if (!resp.ok) throw new Error('planet ephemeris HTTP ' + resp.status);
          return resp.json();
        })
        .then(function(payload) {
          if (!payload || !payload.ok || !applyPlanetEphemeris(payload)) {
            throw new Error((payload && payload.errors || []).join('; ') || 'empty planet ephemeris');
          }
        })
        .catch(function(err) {
          console.warn('Planet ephemeris unavailable, using approximate orbital elements.', err);
          planetStatus = {
            loading: false,
            source: 'approximate orbital elements',
            message: 'fallback planets'
          };
        });
    }

    if (showPlanets) loadPlanetData();

    function resize() {
      var rect = host.getBoundingClientRect();
      var nextDpr = Math.min(window.devicePixelRatio || 1, 2);
      if (rect.width === width && rect.height === height && nextDpr === dpr) return;
      width = Math.max(1, Math.round(rect.width));
      height = Math.max(1, Math.round(rect.height));
      dpr = nextDpr;
      [glCanvas, labelCanvas].forEach(function(canvas) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
      });
      labelCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function wrapLng(lng) {
      return ((lng + 540) % 360) - 180;
    }

    function limbPoint(lng, lat, bearingDeg) {
      var angular = 88.5 * Math.PI / 180;
      var bearing = bearingDeg * Math.PI / 180;
      var lat1 = lat * Math.PI / 180;
      var lon1 = lng * Math.PI / 180;
      var lat2 = Math.asin(Math.sin(lat1) * Math.cos(angular) + Math.cos(lat1) * Math.sin(angular) * Math.cos(bearing));
      var lon2 = lon1 + Math.atan2(
        Math.sin(bearing) * Math.sin(angular) * Math.cos(lat1),
        Math.cos(angular) - Math.sin(lat1) * Math.sin(lat2)
      );
      return [wrapLng(lon2 * 180 / Math.PI), lat2 * 180 / Math.PI];
    }

    function globeScreenGeometry() {
      var center = map.getCenter();
      var centerPoint = map.project(center);
      var distances = [0, 90, 180, 270].map(function(bearing) {
        try {
          var p = map.project(limbPoint(center.lng, center.lat, bearing));
          return Math.hypot(p.x - centerPoint.x, p.y - centerPoint.y);
        } catch (e) {
          return null;
        }
      }).filter(function(distance) {
        return Number.isFinite(distance) && distance > 0;
      });
      distances.sort(function(a, b) { return a - b; });
      var radius = distances.length ? distances[Math.floor(distances.length / 2)] : Math.min(width, height) * 0.18;
      radius = clamp(radius, 24, Math.min(width, height) * 0.48);
      var pitch = clamp(map.getPitch(), 0, 75) * Math.PI / 180 * 0.58;
      var zoom = map.getZoom();
      return {
        x: centerPoint.x,
        y: centerPoint.y,
        r: radius,
        matrix: viewMatrixForCenter(center),
        pitchSin: Math.sin(pitch),
        pitchCos: Math.cos(pitch),
        cameraDistance: clamp(4.8 - zoom * 0.28, 3.35, 4.65),
        centerLng: center.lng,
        centerLat: center.lat
      };
    }

    function previewVisibility(geom, zoom, pitch) {
      var zoomAlpha = 1 - smoothstep(2.55, 3.05, zoom);
      var pitchAlpha = clamp((74 - pitch) / 44, 0, 1);
      var globeFill = geom.r / Math.max(1, Math.min(width, height));
      var wholeGlobeAlpha = 1 - smoothstep(0.43, 0.485, globeFill);
      return clamp(zoomAlpha * pitchAlpha * wholeGlobeAlpha, 0, 1);
    }

    function createStarfield(count) {
      var list = [];
      var seed = 91457;
      function random() {
        seed = (seed * 16807) % 2147483647;
        return (seed - 1) / 2147483646;
      }
      for (var i = 0; i < count; i++) {
        list.push({
          x: random(),
          y: random(),
          size: random() > 0.93 ? 1.45 : 0.75 + random() * 0.65,
          alpha: 0.18 + random() * 0.58,
          blue: random() > 0.72
        });
      }
      return list;
    }

    function drawStarfield(geom, alpha) {
      var lngOffset = ((geom.centerLng % 360) / 360) * width * 0.16;
      var bearingOffset = (map.getBearing() / 360) * width * 0.10;
      labelCtx.save();
      labelCtx.globalAlpha = alpha * 0.48;
      stars.forEach(function(star) {
        var x = (star.x * width + lngOffset + bearingOffset + width) % width;
        var y = (star.y * height + geom.centerLat * 0.15 + height) % height;
        var dx = x - geom.x;
        var dy = y - geom.y;
        if (dx * dx + dy * dy < geom.r * geom.r * 1.12) return;
        labelCtx.fillStyle = star.blue ? 'rgba(172, 203, 255, ' + star.alpha + ')' : 'rgba(255, 255, 255, ' + star.alpha + ')';
        labelCtx.fillRect(x, y, star.size, star.size);
      });
      labelCtx.restore();
    }

    function sunVector(date) {
      var day = date.getTime() / 86400000 - 10957.5;
      var meanLongitude = (280.46 + 0.9856474 * day) * Math.PI / 180;
      var meanAnomaly = (357.528 + 0.9856003 * day) * Math.PI / 180;
      var eclipticLongitude = meanLongitude + (1.915 * Math.sin(meanAnomaly) + 0.020 * Math.sin(2 * meanAnomaly)) * Math.PI / 180;
      var obliquity = (23.439 - 0.0000004 * day) * Math.PI / 180;
      var rightAscension = Math.atan2(Math.cos(obliquity) * Math.sin(eclipticLongitude), Math.cos(eclipticLongitude));
      var declination = Math.asin(Math.sin(obliquity) * Math.sin(eclipticLongitude));
      var gmst = satelliteApi && satelliteApi.gstime ? satelliteApi.gstime(date) : 0;
      var lng = rightAscension - gmst;
      var cosLat = Math.cos(declination);
      return [
        cosLat * Math.sin(lng),
        Math.sin(declination),
        cosLat * Math.cos(lng)
      ];
    }

    function drawLimbShading(geom, alpha, date) {
      var sun = rotateForView(geom, sunVector(date));
      var lightLength = Math.hypot(sun[0], sun[1]) || 1;
      var lx = sun[0] / lightLength;
      var ly = -sun[1] / lightLength;
      var shadeX = geom.x - lx * geom.r * 0.42;
      var shadeY = geom.y - ly * geom.r * 0.42;
      var lightX = geom.x + lx * geom.r * 0.48;
      var lightY = geom.y + ly * geom.r * 0.48;

      labelCtx.save();
      labelCtx.beginPath();
      labelCtx.arc(geom.x, geom.y, geom.r * 1.012, 0, TWO_PI);
      labelCtx.clip();

      var shade = labelCtx.createRadialGradient(shadeX, shadeY, geom.r * 0.12, shadeX, shadeY, geom.r * 1.32);
      shade.addColorStop(0.00, 'rgba(0, 0, 0, ' + (0.22 * alpha).toFixed(3) + ')');
      shade.addColorStop(0.56, 'rgba(0, 0, 0, ' + (0.09 * alpha).toFixed(3) + ')');
      shade.addColorStop(1.00, 'rgba(0, 0, 0, 0)');
      labelCtx.fillStyle = shade;
      labelCtx.fillRect(geom.x - geom.r * 1.2, geom.y - geom.r * 1.2, geom.r * 2.4, geom.r * 2.4);

      var limb = labelCtx.createRadialGradient(lightX, lightY, geom.r * 0.32, geom.x, geom.y, geom.r * 1.04);
      limb.addColorStop(0.00, 'rgba(255, 255, 255, 0)');
      limb.addColorStop(0.72, 'rgba(255, 255, 255, 0)');
      limb.addColorStop(1.00, 'rgba(141, 190, 255, ' + (0.11 * alpha).toFixed(3) + ')');
      labelCtx.fillStyle = limb;
      labelCtx.fillRect(geom.x - geom.r * 1.05, geom.y - geom.r * 1.05, geom.r * 2.1, geom.r * 2.1);
      labelCtx.restore();
    }

    function drawAtmosphere(geom, alpha) {
      var cx = geom.x;
      var cy = geom.y;
      var radius = geom.r;
      var innerRadius = radius * 0.995;
      var outerRadius = radius * 1.095;
      var glow = labelCtx.createRadialGradient(cx, cy, radius * 0.985, cx, cy, outerRadius);
      glow.addColorStop(0.00, 'rgba(111, 168, 255, 0.00)');
      glow.addColorStop(0.34, 'rgba(111, 168, 255, 0.060)');
      glow.addColorStop(0.58, 'rgba(143, 203, 255, 0.23)');
      glow.addColorStop(0.82, 'rgba(107, 168, 255, 0.10)');
      glow.addColorStop(1.00, 'rgba(111, 168, 255, 0.00)');
      labelCtx.save();
      labelCtx.globalAlpha = alpha;
      labelCtx.fillStyle = glow;
      labelCtx.beginPath();
      labelCtx.arc(cx, cy, outerRadius, 0, TWO_PI);
      labelCtx.arc(cx, cy, innerRadius, TWO_PI, 0, true);
      labelCtx.fill('evenodd');
      labelCtx.restore();
    }

    function isOccludedByEarth(geom, projected) {
      var dx = projected.x - geom.x;
      var dy = projected.y - geom.y;
      var insideDisc = dx * dx + dy * dy < geom.r * geom.r * 1.02;
      return insideDisc && projected.z < 0.04;
    }

    function colorToRgba(color, alpha) {
      return 'rgba(' +
        Math.round(color[0] * 255) + ', ' +
        Math.round(color[1] * 255) + ', ' +
        Math.round(color[2] * 255) + ', ' +
        clamp(alpha, 0, 1).toFixed(3) + ')';
    }

    function segmentOutsideViewport(a, b, padding) {
      var minX = Math.min(a.x, b.x);
      var maxX = Math.max(a.x, b.x);
      var minY = Math.min(a.y, b.y);
      var maxY = Math.max(a.y, b.y);
      return maxX < -padding || minX > width + padding || maxY < -padding || minY > height + padding;
    }

    function drawOrbitTail(body, geom, alpha, nowDate, realNowMs) {
      var nowMs = Number.isFinite(realNowMs) ? realNowMs : Date.now();
      var realAge = Math.abs(nowMs - (body.trailBuiltRealAt || 0));
      var simulationAge = Math.abs(nowDate.getTime() - (body.trailBuiltAt || 0));
      var maxSimulationAge = Math.max(1800, (body.trajectoryStepMs || SATELLITE_TRAJECTORY_MIN_STEP_MS) * 0.45);
      if (!body.trailPoints || !body.trailBuiltAt || realAge > orbitTailRebuildMs || simulationAge > maxSimulationAge) {
        buildOrbitTail(body, nowDate);
      }
      if (!body.trailPoints || body.trailPoints.length < 6) return;
      var points = body.trailPoints;
      var currentWorld = sampleSatelliteWorld(body, nowDate);
      var segmentCount = Math.max(1, points.length / 3 - 1);
      labelCtx.save();
      labelCtx.globalCompositeOperation = 'lighter';
      for (var i = segmentCount; i > 0; i--) {
        var idx = i * 3;
        var p0 = [points[idx], points[idx + 1], points[idx + 2]];
        var p1 = currentWorld && i === 1 ? currentWorld : [points[idx - 3], points[idx - 2], points[idx - 1]];
        var a = projectWorldPoint(geom, p0);
        var b = projectWorldPoint(geom, p1);
        var aVisible = !isOccludedByEarth(geom, a);
        var bVisible = !isOccludedByEarth(geom, b);
        if (!aVisible && !bVisible) continue;
        if ((Math.abs(a.x - b.x) + Math.abs(a.y - b.y)) > geom.r * 1.4) continue;
        var tailAge = i / segmentCount;
        var headWeight = Math.pow(1 - tailAge, 1.95);
        var tailFade = smoothstep(1, 0, tailAge);
        var depth = smoothstep(-0.18, 0.82, (a.z + b.z) * 0.5);
        var screenFade = aVisible && bVisible ? 1 : 0.24;
        var segmentAlpha = alpha * ORBIT_LINE_COLOR[3] * (0.05 + 0.95 * headWeight) * (0.26 + 0.74 * depth) * screenFade * tailFade * body.highlight;
        if (segmentAlpha < 0.012) continue;
        labelCtx.strokeStyle = colorToRgba(ORBIT_LINE_COLOR, segmentAlpha);
        labelCtx.lineWidth = clamp(0.42 + headWeight * 1.45 + (a.perspective + b.perspective) * 0.16, 0.45, 2.1);
        labelCtx.beginPath();
        labelCtx.moveTo(a.x, a.y);
        labelCtx.lineTo(b.x, b.y);
        labelCtx.stroke();
      }
      labelCtx.restore();
    }

    function drawSolarOrbitLines(reference, geom, alpha) {
      if (!reference || !reference.planetOrbits || !reference.planetOrbits.length) return;
      labelCtx.save();
      labelCtx.globalCompositeOperation = 'lighter';
      reference.planetOrbits.forEach(function(orbit) {
        var points = orbit.points || [];
        var segmentCount = Math.max(1, points.length / 3 - 1);
        for (var i = 1; i <= segmentCount; i++) {
          var idx = i * 3;
          var p0 = [points[idx - 3], points[idx - 2], points[idx - 1]];
          var p1 = [points[idx], points[idx + 1], points[idx + 2]];
          var a = projectSolarPoint(geom, p0);
          var b = projectSolarPoint(geom, p1);
          if (segmentOutsideViewport(a, b, Math.max(width, height) * 0.35)) continue;
          var lineAlpha = alpha * SOLAR_ORBIT_COLOR[3];
          if (lineAlpha < 0.009) continue;
          labelCtx.strokeStyle = colorToRgba(SOLAR_ORBIT_COLOR, lineAlpha);
          labelCtx.lineWidth = 1.1;
          labelCtx.beginPath();
          labelCtx.moveTo(a.x, a.y);
          labelCtx.lineTo(b.x, b.y);
          labelCtx.stroke();
        }
      });
      labelCtx.restore();
    }

    function drawSunGlyph(reference, geom, alpha) {
      if (!reference || !reference.sunPoint) return null;
      var p = projectSolarPoint(geom, reference.sunPoint);
      var depth = smoothstep(-0.55, 1.05, p.z);
      var pointAlpha = alpha * (0.48 + 0.52 * depth);
      if (pointAlpha < 0.04) return null;
      var size = clamp(7.5 * (0.96 + p.perspective * 0.42), 6.0, 12.5);
      labelCtx.save();
      labelCtx.globalCompositeOperation = 'lighter';
      labelCtx.globalAlpha = pointAlpha;
      labelCtx.shadowColor = 'rgba(255, 238, 40, 0.92)';
      labelCtx.shadowBlur = 14;
      labelCtx.fillStyle = colorToRgba(SUN_COLOR, SUN_COLOR[3]);
      labelCtx.beginPath();
      labelCtx.arc(p.x, p.y, size, 0, TWO_PI);
      labelCtx.fill();
      labelCtx.restore();
      return { x: p.x, y: p.y, z: p.z, alpha: pointAlpha, perspective: p.perspective, label: '太阳' };
    }

    function drawPlanetGlyph(body, geom, nowDate, alpha, scale) {
      var world = samplePlanetWorld(body, nowDate, scale);
      if (!world) return null;
      var p = projectSolarPoint(geom, world);
      var depth = smoothstep(-0.18, 0.92, p.z);
      var earthFade = isOccludedByEarth(geom, p) ? 0.22 : 1;
      var pointAlpha = alpha * (0.32 + 0.68 * depth) * earthFade;
      if (pointAlpha < 0.035) return null;
      var size = clamp(body.size * (1.05 + p.perspective * 0.42), 3.4, 7.2);

      labelCtx.save();
      labelCtx.globalCompositeOperation = 'lighter';
      labelCtx.globalAlpha = pointAlpha;
      labelCtx.fillStyle = colorToRgba(body.color, body.color[3]);
      labelCtx.shadowColor = colorToRgba(body.color, 0.74);
      labelCtx.shadowBlur = body.showLabel ? 8 : 5;
      labelCtx.beginPath();
      labelCtx.arc(p.x, p.y, size, 0, TWO_PI);
      labelCtx.fill();
      labelCtx.restore();
      return { x: p.x, y: p.y, z: p.z, alpha: pointAlpha, perspective: p.perspective, label: body.label };
    }

    function drawPlanetLabel(body, projected, alpha) {
      if (!projected || !body.showLabel) return;
      var labelAlpha = alpha * clamp(0.20 + projected.alpha * 0.72, 0, 1);
      if (labelAlpha < 0.05) return;
      labelCtx.save();
      labelCtx.globalAlpha = labelAlpha;
      labelCtx.font = '600 10px Noto Sans SC, sans-serif';
      labelCtx.textBaseline = 'middle';
      labelCtx.fillStyle = 'rgba(232, 236, 242, 0.86)';
      labelCtx.shadowColor = '#000000';
      labelCtx.shadowBlur = 4;
      labelCtx.fillText(body.label, projected.x + 8, projected.y - 7);
      labelCtx.restore();
    }

    function drawSpacecraftGlyph(body, geom, date, alpha) {
      var frame = sampleSatelliteFrame(body, date);
      if (!frame || !frame.position) return null;
      var world = frame.position;
      var p = projectWorldPoint(geom, world);
      if (isOccludedByEarth(geom, p)) return null;
      var velocity = frame.velocity || [0, 0, 0];
      var hasVelocity = Math.hypot(velocity[0], velocity[1], velocity[2]) > 1e-7;
      var next = hasVelocity
        ? [world[0] + velocity[0] * 45, world[1] + velocity[1] * 45, world[2] + velocity[2] * 45]
        : sampleSatelliteWorld(body, new Date(date.getTime() + 45000));
      var nextProjected = next ? projectWorldPoint(geom, next) : null;
      var angle = nextProjected ? Math.atan2(nextProjected.y - p.y, nextProjected.x - p.x) : 0;
      var depth = smoothstep(-0.10, 0.82, p.z);
      var glyphAlpha = alpha * (0.38 + 0.62 * depth);
      var size = clamp(body.size * 0.64 * p.perspective, 2.5, body.showLabel ? 4.6 : 3.8);

      labelCtx.save();
      labelCtx.translate(p.x, p.y);
      labelCtx.rotate(angle + Math.PI / 6);
      labelCtx.globalAlpha = glyphAlpha;
      labelCtx.strokeStyle = 'rgba(210, 214, 218, 0.86)';
      labelCtx.lineWidth = body.showLabel ? 0.9 : 0.72;
      labelCtx.shadowColor = '#000000';
      labelCtx.shadowBlur = 4;
      labelCtx.beginPath();
      for (var i = 0; i < 6; i++) {
        var a = Math.PI / 3 * i;
        var hx = Math.cos(a) * size;
        var hy = Math.sin(a) * size;
        if (i === 0) labelCtx.moveTo(hx, hy);
        else labelCtx.lineTo(hx, hy);
      }
      labelCtx.closePath();
      labelCtx.stroke();
      labelCtx.restore();
      return { x: p.x, y: p.y, z: p.z, alpha: glyphAlpha, perspective: p.perspective };
    }

    function drawLabel(body, projected, alpha) {
      if (!projected || !body.showLabel) return;
      var labelAlpha = alpha * clamp(0.30 + projected.alpha * 0.72, 0, 1);
      if (labelAlpha < 0.05) return;
      var labelX = projected.x + 8;
      var labelY = projected.y - 6;
      labelCtx.save();
      labelCtx.globalAlpha = labelAlpha;
      labelCtx.font = '600 9px Noto Sans SC, sans-serif';
      labelCtx.textBaseline = 'middle';
      labelCtx.strokeStyle = 'rgba(188, 210, 238, 0.42)';
      labelCtx.lineWidth = 1;
      labelCtx.beginPath();
      labelCtx.moveTo(projected.x + 3, projected.y - 2);
      labelCtx.lineTo(labelX - 2, labelY);
      labelCtx.stroke();
      labelCtx.fillStyle = 'rgba(226, 236, 250, 0.90)';
      labelCtx.shadowColor = '#000000';
      labelCtx.shadowBlur = 4;
      labelCtx.fillText(body.label, labelX, labelY);
      labelCtx.restore();
    }

    function drawOrbitPoint(body, geom, nowDate, pointAlpha) {
      var point = sampleSatelliteWorld(body, nowDate);
      if (!point) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, pointBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(point), gl.DYNAMIC_DRAW);
      useProgram(pointInfo, geom, [body.color[0], body.color[1], body.color[2], body.color[3] * pointAlpha]);
      setPositionAttribute(pointInfo, pointBuffer);
      gl.uniform1f(pointInfo.pointSize, body.size * dpr);
      gl.drawArrays(gl.POINTS, 0, 1);
    }

    function drawDepthSphere(geom) {
      useProgram(lineInfo, geom, [0, 0, 0, 0]);
      setPositionAttribute(lineInfo, sphereBuffer);
      gl.colorMask(false, false, false, false);
      gl.depthMask(true);
      gl.disable(gl.BLEND);
      gl.enable(gl.CULL_FACE);
      gl.cullFace(gl.BACK);
      gl.drawArrays(gl.TRIANGLES, 0, sphereVertexCount);
      gl.disable(gl.CULL_FACE);
      gl.colorMask(true, true, true, true);
      gl.depthMask(false);
    }

    function drawOrbitStatus(alpha) {
      var parts = [];
      if (orbitStatus && orbitStatus.message) parts.push(orbitStatus.source + ' - ' + orbitStatus.message);
      if (showPlanets && planetStatus && planetStatus.message) parts.push(planetStatus.source + ' - ' + planetStatus.message);
      if (!parts.length) return;
      var text = parts.join(' | ');
      labelCtx.save();
      labelCtx.globalAlpha = alpha * 0.62;
      labelCtx.font = '600 10px Noto Sans SC, sans-serif';
      labelCtx.textBaseline = 'top';
      labelCtx.textAlign = 'right';
      labelCtx.fillStyle = 'rgba(218, 232, 255, 0.82)';
      labelCtx.shadowColor = '#000000';
      labelCtx.shadowBlur = 4;
      labelCtx.fillText(text, width - 18, 16);
      labelCtx.restore();
    }

    function draw() {
      if (destroyed) return;
      resize();
      var zoom = map.getZoom();
      var pitch = map.getPitch();
      var geom = globeScreenGeometry();
      var alpha = previewVisibility(geom, zoom, pitch);
      var realNowMs = Date.now();
      var nowDate = simulationDate(realNowMs);

      gl.viewport(0, 0, glCanvas.width, glCanvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clearDepth(1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      labelCtx.clearRect(0, 0, width, height);

      if (alpha > 0.015) {
        drawStarfield(geom, alpha);

        gl.enable(gl.DEPTH_TEST);
        gl.depthFunc(gl.LEQUAL);
        drawDepthSphere(geom);
        gl.enable(gl.BLEND);
        gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
        spaceBodies.forEach(function(body) {
          drawOrbitPoint(body, geom, nowDate, alpha * 0.72);
        });

        drawLimbShading(geom, alpha, nowDate);
        drawAtmosphere(geom, alpha);
        spaceBodies.forEach(function(body) {
          drawOrbitTail(body, geom, alpha, nowDate, realNowMs);
        });
        if (showPlanets) {
          var planetScale = solarSystemScale(nowDate);
          var solarFrame = getSolarReference(nowDate, planetScale);
          drawSolarOrbitLines(solarFrame, geom, alpha * 0.78);
          var sunProjected = drawSunGlyph(solarFrame, geom, alpha);
          var planetLabels = [];
          planetBodies.forEach(function(body) {
            planetLabels.push({ body: body, projected: drawPlanetGlyph(body, geom, nowDate, alpha * 0.88, planetScale) });
          });
          planetLabels.forEach(function(item) {
            drawPlanetLabel(item.body, item.projected, alpha);
          });
          drawPlanetLabel({ label: '太阳', showLabel: true }, sunProjected, alpha);
        }
        spaceBodies.forEach(function(body) {
          var projected = drawSpacecraftGlyph(body, geom, nowDate, alpha);
          drawLabel(body, projected, alpha);
        });
        drawOrbitStatus(alpha);
      }

      animationFrame = requestAnimationFrame(draw);
    }

    resize();
    animationFrame = requestAnimationFrame(draw);

    return {
      destroy: function() {
        destroyed = true;
        if (animationFrame) window.cancelAnimationFrame(animationFrame);
        removeCanvases();
      }
    };
  }

  window.VirtualCityOrbitPreview = {
    mount: mount
  };
})();
