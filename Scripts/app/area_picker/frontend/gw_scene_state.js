// Domain: game-workbench / scene-state
// Owns: the characters/sceneModels/whiteboxLayers arrays -- scene.add/remove wiring,
//       pickable + outline list derivation, and localStorage-shaped serialization.
// AI handoff: for "场景对象数量与列表不一致" 类 bug 先看这里；选中状态、撤销历史、
//             大纲 UI 渲染仍在 game_workbench.js（撤销栈见 gw_history.js）。
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});

  GW.createSceneState = function(ctx) {
    var getScene = ctx.getScene;
    var characters = [];
    var sceneModels = [];
    var whiteboxLayers = [];

    function refreshWhiteboxLayers() {
      whiteboxLayers = [];
      sceneModels.forEach(function(model) {
        (model.layers || []).forEach(function(layer) { whiteboxLayers.push(layer); });
      });
    }

    function addCharacter(character, index) {
      if (typeof index === 'number' && index >= 0) characters.splice(index, 0, character);
      else if (characters.indexOf(character) < 0) characters.push(character);
      getScene().add(character);
    }

    function removeCharacter(character) {
      var index = characters.indexOf(character);
      if (index >= 0) characters.splice(index, 1);
      getScene().remove(character);
      return index;
    }

    function addModel(model, index) {
      if (!model || !model.root) return null;
      if (typeof index === 'number' && index >= 0) sceneModels.splice(index, 0, model);
      else if (sceneModels.indexOf(model) < 0) sceneModels.push(model);
      getScene().add(model.root);
      refreshWhiteboxLayers();
      return model;
    }

    function removeModel(model) {
      if (!model || !model.root) return -1;
      var index = sceneModels.indexOf(model);
      if (index >= 0) sceneModels.splice(index, 1);
      getScene().remove(model.root);
      refreshWhiteboxLayers();
      return index;
    }

    function belongsToModel(object, model) {
      if (!object || !model) return false;
      var root = object.userData && object.userData.assetRoot ? object.userData.assetRoot : object;
      return root === model.root || (model.layers || []).indexOf(root) >= 0;
    }

    // Reverse lookup used by rename: given a picked root/layer, find the model
    // wrapper it belongs to so its persisted `.label` can be kept in sync with
    // the userData.assetLabel the outliner displays.
    function findModelFor(object) {
      for (var i = 0; i < sceneModels.length; i++) {
        if (belongsToModel(object, sceneModels[i])) return sceneModels[i];
      }
      return null;
    }

    // A model with imported whitebox layers exposes those layers as its pick/outline
    // targets; a plain GLB model exposes just its root. Shared by getPickables and
    // getOutlineItems so a new wrapped-object kind only has to reuse this, not both.
    function flattenModels() {
      var flat = [];
      sceneModels.forEach(function(model) {
        if (model.layers && model.layers.length) {
          model.layers.forEach(function(layer) { flat.push(layer); });
        } else if (model.root) {
          flat.push(model.root);
        }
      });
      return flat;
    }

    function getPickables() {
      return characters.concat(flattenModels());
    }

    function getOutlineItems() {
      return flattenModels().concat(characters);
    }

    function serialize() {
      return {
        v: 1,
        models: sceneModels.map(function(model) {
          return {
            url: model.url,
            label: model.label,
            p: model.root.position.toArray(),
            r: [model.root.rotation.x, model.root.rotation.y, model.root.rotation.z],
            s: model.root.scale.toArray()
          };
        }),
        characters: characters.map(function(character) {
          return {
            p: character.position.toArray(),
            r: [character.rotation.x, character.rotation.y, character.rotation.z],
            s: character.scale.toArray(),
            label: character.userData.assetLabel || null
          };
        })
      };
    }

    function clear() {
      var scene = getScene();
      characters.slice().forEach(function(character) { scene.remove(character); });
      characters = [];
      sceneModels.slice().forEach(function(model) { scene.remove(model.root); });
      sceneModels = [];
      whiteboxLayers = [];
    }

    return {
      getCharacters: function() { return characters; },
      getWhiteboxLayers: function() { return whiteboxLayers; },
      addCharacter: addCharacter,
      removeCharacter: removeCharacter,
      addModel: addModel,
      removeModel: removeModel,
      belongsToModel: belongsToModel,
      findModelFor: findModelFor,
      getPickables: getPickables,
      getOutlineItems: getOutlineItems,
      serialize: serialize,
      clear: clear
    };
  };
})();
