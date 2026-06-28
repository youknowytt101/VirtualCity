// Domain: shared-glb-loading
// Owns: GLB loader reuse for the editor scene and Houdini preview.
// AI handoff: If a whitebox or game GLB URL loads incorrectly, check this after the caller's URL contract.
// Shared GLB loader for the editor scene and the Houdini preview.
// Returns the loaded scene rotated from glTF Y-up to this app's Z-up.
(function() {
  'use strict';
  var loader = null;

  function load(url) {
    return import('/static/three/GLTFLoader.js').then(function(mod) {
      if (!loader) loader = new mod.GLTFLoader();
      return new Promise(function(resolve, reject) {
        loader.load(url, function(gltf) {
          var root = gltf.scene;
          root.rotation.x = Math.PI / 2;  // glTF Y-up -> scene Z-up
          root.updateMatrixWorld(true);
          resolve(root);
        }, undefined, reject);
      });
    });
  }

  window.VC_GLB = { load: load };
})();
