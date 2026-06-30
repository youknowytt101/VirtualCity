// Domain: game-editor-legacy-bridge
// Owns: compatibility bridge from the existing global workbench to the editor core.

import { createEditorApp } from './editor_app.js';
import { createLegacyWorkbenchSync } from './legacy_sync.js';

var legacyWorkbench = window.VC_GAME_WORKBENCH || {};
var app = createEditorApp({ legacyWorkbench: legacyWorkbench });

window.VC_GAME_EDITOR_APP = app;
window.VC_GAME_EDITOR_SYNC = createLegacyWorkbenchSync(app.getEditorState());
window.VC_GAME_WORKBENCH = app.getPublicApi();
