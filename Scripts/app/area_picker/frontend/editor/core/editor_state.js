// Domain: game-editor-state
// Owns: SceneDocument store, subscriptions, dispatch, undo, and redo.

import {
  createSceneDocument,
  setEditorMode
} from './scene_document.js';

export function createEditorState(initialDocument) {
  var document = createSceneDocument(initialDocument);
  var listeners = [];
  var undoStack = [];
  var redoStack = [];

  function notify(command) {
    var event = { document: document, command: command || null };
    listeners.slice().forEach(function(listener) {
      listener(event);
    });
  }

  function getDocument() {
    return document;
  }

  function getSelection() {
    return document.selection.ids.slice();
  }

  function getEditorMode() {
    return document.editor.mode;
  }

  function setEditorModeValue(mode) {
    document = setEditorMode(document, mode);
    redoStack = [];
    notify({ type: 'set-editor-mode', changesDocument: true });
    return document;
  }

  function dispatch(command) {
    if (!command || typeof command.execute !== 'function') {
      throw new Error('EditorState dispatch requires a command');
    }
    var nextDocument = command.execute(document);
    if (!nextDocument) return document;
    document = createSceneDocument(nextDocument);
    if (command.changesDocument !== false && typeof command.undo === 'function') {
      undoStack.push(command);
      redoStack = [];
    }
    notify(command);
    return document;
  }

  function undo() {
    var command = undoStack.pop();
    if (!command || typeof command.undo !== 'function') return document;
    document = createSceneDocument(command.undo(document));
    redoStack.push(command);
    notify({ type: 'undo', command: command, changesDocument: true });
    return document;
  }

  function redo() {
    var command = redoStack.pop();
    if (!command || typeof command.execute !== 'function') return document;
    document = createSceneDocument(command.execute(document));
    undoStack.push(command);
    notify({ type: 'redo', command: command, changesDocument: true });
    return document;
  }

  function subscribe(listener) {
    if (typeof listener !== 'function') return function() {};
    listeners.push(listener);
    return function unsubscribe() {
      listeners = listeners.filter(function(item) { return item !== listener; });
    };
  }

  return {
    getDocument: getDocument,
    getSelection: getSelection,
    getEditorMode: getEditorMode,
    setEditorMode: setEditorModeValue,
    dispatch: dispatch,
    undo: undo,
    redo: redo,
    subscribe: subscribe
  };
}
