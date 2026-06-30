// Domain: game-editor-legacy-sync
// Owns: translation from the classic Three.js workbench objects into editor-core commands.

import {
  AddEntityCommand,
  DeleteSelectionCommand,
  ImportWhiteboxCommand,
  SetSelectionCommand,
  SetTransformModeCommand
} from './core/commands.js';

function clonePlain(value, fallback) {
  if (value === undefined || value === null) return fallback;
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (error) {
    return fallback;
  }
}

function numeric(value, fallback) {
  var next = Number(value);
  return Number.isFinite(next) ? next : fallback;
}

function vectorToArray(value, fallback) {
  var base = fallback || [0, 0, 0];
  if (Array.isArray(value)) {
    return [
      numeric(value[0], base[0]),
      numeric(value[1], base[1]),
      numeric(value[2], base[2])
    ];
  }
  if (value && typeof value === 'object') {
    return [
      numeric(value.x, base[0]),
      numeric(value.y, base[1]),
      numeric(value.z, base[2])
    ];
  }
  return base.slice(0, 3);
}

function transformFromObject(object) {
  object = object || {};
  return {
    position: vectorToArray(object.position, [0, 0, 0]),
    rotation: vectorToArray(object.rotation, [0, 0, 0]),
    scale: vectorToArray(object.scale, [1, 1, 1])
  };
}

function entityIdFromObject(object) {
  var userData = object && object.userData ? object.userData : {};
  return String(userData.entityId || object && object.name || '').trim();
}

function characterEntityFromObject(character) {
  var id = entityIdFromObject(character);
  if (!id) return null;
  return {
    id: id,
    type: 'character',
    name: character.name || id,
    assetRef: 'builtin:character',
    transform: transformFromObject(character),
    collider: clonePlain(character.userData && character.userData.collider, null)
  };
}

function whiteboxLayerEntityFromObject(layer) {
  var id = entityIdFromObject(layer);
  if (!id) return null;
  var userData = layer.userData || {};
  return {
    id: id,
    type: 'whiteboxLayer',
    name: userData.assetLabel || layer.name || id,
    assetRef: 'houdini:whitebox.glb#' + (userData.assetType || id),
    transform: transformFromObject(layer),
    collision: {
      enabled: userData.collisionEnabled !== false,
      role: userData.collisionRole || 'walkable',
      shape: userData.collisionShape || 'triangle-mesh'
    }
  };
}

function dispatch(editorState, command) {
  if (!editorState || typeof editorState.dispatch !== 'function' || !command) return null;
  return editorState.dispatch(command);
}

export function createLegacyWorkbenchSync(editorState) {
  function characterAdded(character) {
    var entity = characterEntityFromObject(character);
    return dispatch(editorState, entity ? AddEntityCommand(entity) : null);
  }

  function characterDeleted(character) {
    var id = entityIdFromObject(character);
    if (!id) return null;
    dispatch(editorState, SetSelectionCommand([id]));
    return dispatch(editorState, DeleteSelectionCommand([id]));
  }

  function selectionChanged(object) {
    var id = entityIdFromObject(object);
    return dispatch(editorState, SetSelectionCommand(id ? [id] : []));
  }

  function transformModeChanged(mode) {
    return dispatch(editorState, SetTransformModeCommand(mode));
  }

  function whiteboxImported(layers) {
    var entities = Array.prototype.slice.call(layers || [])
      .map(whiteboxLayerEntityFromObject)
      .filter(Boolean);
    return dispatch(editorState, ImportWhiteboxCommand(entities));
  }

  return {
    characterAdded: characterAdded,
    characterDeleted: characterDeleted,
    selectionChanged: selectionChanged,
    transformModeChanged: transformModeChanged,
    whiteboxImported: whiteboxImported
  };
}
