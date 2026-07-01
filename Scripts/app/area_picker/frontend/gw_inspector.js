// Domain: game-workbench / inspector
// Owns: the "细节" tab's numeric transform panel (position/rotation/scale) and the
//       selected object's rename field. Pure DOM binding; game_workbench.js supplies
//       ctx (selection getter, transform capture/commit, rename).
// AI handoff: for "数值面板不更新" / "改名不生效" 类 bug，先看这里，再看 game_workbench.js。
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var RAD2DEG = 180 / Math.PI;
  var DEG2RAD = Math.PI / 180;

  function round(n) {
    return Math.round(n * 1000) / 1000;
  }

  GW.createInspector = function(ctx) {
    var emptyHint = document.getElementById('inspector-empty-hint');
    var body = document.getElementById('inspector-body');
    var nameInput = document.getElementById('inspector-name');
    var fields = {
      px: document.getElementById('inspector-pos-x'),
      py: document.getElementById('inspector-pos-y'),
      pz: document.getElementById('inspector-pos-z'),
      rx: document.getElementById('inspector-rot-x'),
      ry: document.getElementById('inspector-rot-y'),
      rz: document.getElementById('inspector-rot-z'),
      sx: document.getElementById('inspector-scale-x'),
      sy: document.getElementById('inspector-scale-y'),
      sz: document.getElementById('inspector-scale-z')
    };
    if (!emptyHint || !body || !nameInput || !fields.px) {
      return { refresh: function() {}, sync: function() {} };
    }

    var current = null;
    var editing = false;

    function fillFromObject(object) {
      nameInput.value = object.userData.assetLabel || object.name || '';
      fields.px.value = round(object.position.x);
      fields.py.value = round(object.position.y);
      fields.pz.value = round(object.position.z);
      fields.rx.value = round(object.rotation.x * RAD2DEG);
      fields.ry.value = round(object.rotation.y * RAD2DEG);
      fields.rz.value = round(object.rotation.z * RAD2DEG);
      fields.sx.value = round(object.scale.x);
      fields.sy.value = round(object.scale.y);
      fields.sz.value = round(object.scale.z);
    }

    function refresh() {
      var object = ctx.getSelectedObject();
      current = object || null;
      editing = false;
      if (!object) {
        emptyHint.hidden = false;
        body.hidden = true;
        return;
      }
      emptyHint.hidden = true;
      body.hidden = false;
      fillFromObject(object);
    }

    // Called from the render loop while an object is selected (including mid gizmo
    // drag) so the panel stays live without touching focus/selection state -- this
    // must not fight the user while they're actively typing in a field.
    function sync() {
      if (!current || editing) return;
      fillFromObject(current);
    }

    function commitTransform() {
      if (!current) return;
      var before = ctx.captureTransform(current);
      current.position.set(
        parseFloat(fields.px.value) || 0,
        parseFloat(fields.py.value) || 0,
        parseFloat(fields.pz.value) || 0
      );
      current.rotation.set(
        (parseFloat(fields.rx.value) || 0) * DEG2RAD,
        (parseFloat(fields.ry.value) || 0) * DEG2RAD,
        (parseFloat(fields.rz.value) || 0) * DEG2RAD
      );
      current.scale.set(
        parseFloat(fields.sx.value) || 1,
        parseFloat(fields.sy.value) || 1,
        parseFloat(fields.sz.value) || 1
      );
      current.updateMatrixWorld(true);
      ctx.commitTransform(current, before);
    }

    Object.keys(fields).forEach(function(key) {
      var input = fields[key];
      input.addEventListener('focus', function() { editing = true; });
      input.addEventListener('blur', function() { editing = false; commitTransform(); });
      input.addEventListener('keydown', function(event) {
        if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
      });
    });
    nameInput.addEventListener('focus', function() { editing = true; });
    nameInput.addEventListener('blur', function() {
      editing = false;
      if (current && nameInput.value.trim()) ctx.renameObject(current, nameInput.value.trim());
    });
    nameInput.addEventListener('keydown', function(event) {
      if (event.key === 'Enter') { event.preventDefault(); nameInput.blur(); }
    });

    return { refresh: refresh, sync: sync };
  };
})();
