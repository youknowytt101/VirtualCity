// Domain: game-editor-commands
// Owns: document-changing command primitives for the game editor core.

import {
  addEntity,
  deleteEntities,
  duplicateEntities,
  importWhiteboxLayers,
  setEntityTransform,
  setSelection,
  setTransformMode
} from './scene_document.js';

function createDocumentCommand(type, apply) {
  var previousDocument = null;
  return {
    type: type,
    changesDocument: true,
    execute: function(document) {
      previousDocument = document;
      return apply(document);
    },
    undo: function(document) {
      return previousDocument || document;
    }
  };
}

export function AddEntityCommand(entity) {
  return createDocumentCommand('add-entity', function(document) {
    return addEntity(document, entity);
  });
}

export function DeleteSelectionCommand(ids) {
  return createDocumentCommand('delete-selection', function(document) {
    var selection = ids || (document.selection && document.selection.ids) || [];
    return deleteEntities(document, selection);
  });
}

export function DuplicateSelectionCommand(ids) {
  return createDocumentCommand('duplicate-selection', function(document) {
    var selection = ids || (document.selection && document.selection.ids) || [];
    return duplicateEntities(document, selection);
  });
}

export function SetSelectionCommand(ids) {
  return createDocumentCommand('set-selection', function(document) {
    return setSelection(document, ids);
  });
}

export function SetTransformModeCommand(mode) {
  return createDocumentCommand('set-transform-mode', function(document) {
    return setTransformMode(document, mode);
  });
}

export function TransformEntityCommand(id, transform) {
  return createDocumentCommand('transform-entity', function(document) {
    return setEntityTransform(document, id, transform);
  });
}

export function ImportWhiteboxCommand(layers) {
  return createDocumentCommand('import-whitebox', function(document) {
    return importWhiteboxLayers(document, layers);
  });
}
