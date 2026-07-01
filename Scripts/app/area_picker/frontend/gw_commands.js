// Domain: game-workbench / commands
// Owns: reversible scene edit command factories. The history stack stays in
//       gw_history.js; this module only builds undo/redo closures.
// AI handoff: For undo/redo semantics of create/delete/transform, start here.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});

  GW.createSceneCommands = function(ctx) {
    function makeCreateCharacterCommand(character) {
      return {
        undo: function() { ctx.removeCharacter(character); },
        redo: function() {
          ctx.addCharacter(character);
          ctx.selectSceneObject(character);
          ctx.rebuildSceneOutline();
        }
      };
    }

    function makeDeleteCharacterCommand(character, index) {
      return {
        undo: function() {
          ctx.addCharacter(character, index);
          ctx.selectSceneObject(character);
          ctx.rebuildSceneOutline();
        },
        redo: function() { ctx.removeCharacter(character); }
      };
    }

    function makeCreateModelCommand(model) {
      return {
        undo: function() { ctx.removeSceneModel(model, { skipHistory: true }); },
        redo: function() { ctx.addSceneModel(model, { skipHistory: true }); }
      };
    }

    function makeDeleteModelCommand(model, index) {
      return {
        undo: function() {
          ctx.addSceneModel(model, { index: index, skipHistory: true });
          ctx.selectSceneObject(ctx.getModelSelectionTarget(model));
          ctx.rebuildSceneOutline();
        },
        redo: function() { ctx.removeSceneModel(model, { skipHistory: true }); }
      };
    }

    function makeTransformCommand(object, before, after) {
      return {
        undo: function() {
          ctx.applyTransform(object, before);
          ctx.refreshAfterTransform(object);
        },
        redo: function() {
          ctx.applyTransform(object, after);
          ctx.refreshAfterTransform(object);
        }
      };
    }

    return {
      makeCreateCharacterCommand: makeCreateCharacterCommand,
      makeCreateModelCommand: makeCreateModelCommand,
      makeDeleteCharacterCommand: makeDeleteCharacterCommand,
      makeDeleteModelCommand: makeDeleteModelCommand,
      makeTransformCommand: makeTransformCommand
    };
  };
})();
