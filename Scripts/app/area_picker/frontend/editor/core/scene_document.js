// Domain: game-editor-scene-document
// Owns: plain data model helpers for the game editor core.

var DEFAULT_EDITOR_STATE = {
  mode: 'edit',
  transformMode: 'translate',
  activeTool: 'select'
};

function clonePlain(value) {
  if (value === undefined || value === null) return value;
  return JSON.parse(JSON.stringify(value));
}

function uniqueStrings(values) {
  var seen = {};
  var result = [];
  (values || []).forEach(function(value) {
    if (typeof value !== 'string' || !value || seen[value]) return;
    seen[value] = true;
    result.push(value);
  });
  return result;
}

function normalizeTransform(transform) {
  var source = transform || {};
  return {
    position: Array.isArray(source.position) ? source.position.slice(0, 3) : [0, 0, 0],
    rotation: Array.isArray(source.rotation) ? source.rotation.slice(0, 3) : [0, 0, 0],
    scale: Array.isArray(source.scale) ? source.scale.slice(0, 3) : [1, 1, 1]
  };
}

function normalizeEntity(entity) {
  var next = Object.assign({}, clonePlain(entity || {}));
  next.id = String(next.id || '').trim();
  if (!next.id) throw new Error('Scene entity requires id');
  next.type = next.type || 'entity';
  next.name = next.name || next.id;
  next.transform = normalizeTransform(next.transform);
  return next;
}

function normalizeDocument(document) {
  var source = document || {};
  return {
    version: Number(source.version) || 1,
    entities: (source.entities || []).map(normalizeEntity),
    selection: {
      ids: uniqueStrings(source.selection && source.selection.ids)
    },
    editor: Object.assign({}, DEFAULT_EDITOR_STATE, clonePlain(source.editor || {}))
  };
}

function nextCopyId(document, id) {
  var base = id + '-copy';
  var existing = {};
  document.entities.forEach(function(entity) { existing[entity.id] = true; });
  if (!existing[base]) return base;
  var index = 2;
  while (existing[base + '-' + index]) index += 1;
  return base + '-' + index;
}

export function createSceneDocument(seed) {
  return normalizeDocument(seed);
}

export function cloneSceneDocument(document) {
  return normalizeDocument(clonePlain(document));
}

export function getEntityById(document, id) {
  var normalized = createSceneDocument(document);
  for (var i = 0; i < normalized.entities.length; i++) {
    if (normalized.entities[i].id === id) return normalized.entities[i];
  }
  return null;
}

export function addEntity(document, entity) {
  var normalized = createSceneDocument(document);
  var nextEntity = normalizeEntity(entity);
  var entities = normalized.entities.filter(function(existing) {
    return existing.id !== nextEntity.id;
  });
  entities.push(nextEntity);
  return Object.assign({}, normalized, { entities: entities });
}

export function deleteEntities(document, ids) {
  var normalized = createSceneDocument(document);
  var remove = {};
  uniqueStrings(ids).forEach(function(id) { remove[id] = true; });
  return Object.assign({}, normalized, {
    entities: normalized.entities.filter(function(entity) { return !remove[entity.id]; }),
    selection: {
      ids: normalized.selection.ids.filter(function(id) { return !remove[id]; })
    }
  });
}

export function duplicateEntities(document, ids) {
  var normalized = createSceneDocument(document);
  var targets = {};
  uniqueStrings(ids).forEach(function(id) { targets[id] = true; });
  var additions = [];
  normalized.entities.forEach(function(entity) {
    if (!targets[entity.id]) return;
    var copy = normalizeEntity(entity);
    copy.id = nextCopyId({
      entities: normalized.entities.concat(additions)
    }, entity.id);
    copy.name = (entity.name || entity.id) + ' Copy';
    additions.push(copy);
  });
  return Object.assign({}, normalized, {
    entities: normalized.entities.concat(additions),
    selection: { ids: additions.map(function(entity) { return entity.id; }) }
  });
}

export function setSelection(document, ids) {
  var normalized = createSceneDocument(document);
  var existing = {};
  normalized.entities.forEach(function(entity) { existing[entity.id] = true; });
  return Object.assign({}, normalized, {
    selection: {
      ids: uniqueStrings(ids).filter(function(id) { return existing[id]; })
    }
  });
}

export function setTransformMode(document, mode) {
  var normalized = createSceneDocument(document);
  var allowed = { translate: true, rotate: true, scale: true };
  var nextMode = allowed[mode] ? mode : normalized.editor.transformMode;
  return Object.assign({}, normalized, {
    editor: Object.assign({}, normalized.editor, { transformMode: nextMode })
  });
}

export function setEditorMode(document, mode) {
  var normalized = createSceneDocument(document);
  var nextMode = mode === 'play' ? 'play' : 'edit';
  return Object.assign({}, normalized, {
    editor: Object.assign({}, normalized.editor, { mode: nextMode })
  });
}

export function setEntityTransform(document, id, transform) {
  var normalized = createSceneDocument(document);
  return Object.assign({}, normalized, {
    entities: normalized.entities.map(function(entity) {
      if (entity.id !== id) return entity;
      return Object.assign({}, entity, { transform: normalizeTransform(transform) });
    })
  });
}

export function importWhiteboxLayers(document, layers) {
  var normalized = createSceneDocument(document);
  var nonWhitebox = normalized.entities.filter(function(entity) {
    return entity.type !== 'whiteboxLayer';
  });
  var whiteboxLayers = (layers || []).map(function(layer) {
    var next = normalizeEntity(Object.assign({
      type: 'whiteboxLayer',
      collision: {
        enabled: true,
        role: 'walkable',
        shape: 'triangle-mesh'
      }
    }, layer || {}));
    next.type = 'whiteboxLayer';
    return next;
  });
  return Object.assign({}, normalized, {
    entities: nonWhitebox.concat(whiteboxLayers),
    selection: { ids: [] }
  });
}
