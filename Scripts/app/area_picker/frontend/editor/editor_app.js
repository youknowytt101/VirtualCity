// Domain: game-editor-app
// Owns: new editor core composition and compatibility delegation to the legacy workbench.

import { createEditorState } from './core/editor_state.js';

function callLegacy(legacyWorkbench, name, args) {
  var fn = legacyWorkbench && legacyWorkbench[name];
  if (typeof fn !== 'function') return undefined;
  return fn.apply(legacyWorkbench, args || []);
}

export function createEditorApp(options) {
  var legacyWorkbench = options && options.legacyWorkbench ? options.legacyWorkbench : {};
  var editorState = createEditorState();

  function init() {
    return callLegacy(legacyWorkbench, 'init');
  }

  function resize() {
    return callLegacy(legacyWorkbench, 'resize');
  }

  function setActive(active) {
    return callLegacy(legacyWorkbench, 'setActive', [active]);
  }

  function loadGLB(url) {
    return callLegacy(legacyWorkbench, 'loadGLB', [url]);
  }

  function syncFromHoudini() {
    return callLegacy(legacyWorkbench, 'syncFromHoudini');
  }

  function getEditorState() {
    return editorState;
  }

  function dispatch(command) {
    return editorState.dispatch(command);
  }

  function getPublicApi() {
    return {
      init: init,
      resize: resize,
      setActive: setActive,
      loadGLB: loadGLB,
      syncFromHoudini: syncFromHoudini,
      getEditorState: getEditorState,
      dispatch: dispatch
    };
  }

  return {
    legacyWorkbench: legacyWorkbench,
    init: init,
    resize: resize,
    setActive: setActive,
    loadGLB: loadGLB,
    syncFromHoudini: syncFromHoudini,
    getEditorState: getEditorState,
    dispatch: dispatch,
    getPublicApi: getPublicApi
  };
}
