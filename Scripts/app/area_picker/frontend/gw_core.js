// Domain: game-workbench / core
// Owns: the VC_GW namespace, the shared editor-state container, and base helpers
//       (safeThree, setStatus) used across the split game-workbench modules.
// AI handoff: Every gw_*.js module hangs its exports on window.VC_GW and reads
//             shared mutable scene state from VC_GW.state. This file must load first.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});

  // Single shared mutable-state container. The split modules all read/write
  // through GW.state so they observe the same scene/camera/selection. The host
  // (game_workbench.js) populates these during initGameWorkbench().
  GW.state = GW.state || {
    statusText: null
  };

  GW.setStatus = function(message) {
    if (!GW.state.statusText) return;
    GW.state.statusText.textContent = message || '';
    GW.state.statusText.hidden = !message;
  };

  GW.safeThree = function() {
    if (!window.THREE) {
      GW.setStatus('Three.js 未加载');
      return null;
    }
    return window.THREE;
  };
})();
