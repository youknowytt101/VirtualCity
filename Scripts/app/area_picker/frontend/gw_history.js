// Domain: game-workbench / history
// Owns: the generic undo/redo command stack (push/undo/redo/clear). game_workbench.js
//       still builds the { undo, redo } closures per edit and pushes them here.
// AI handoff: For Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z bugs, start here before game_workbench.js.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});

  GW.createHistory = function() {
    var undoStack = [];
    var redoStack = [];

    function push(command) {
      undoStack.push(command);
      redoStack.length = 0;
    }

    function undo() {
      var command = undoStack.pop();
      if (!command) return false;
      command.undo();
      redoStack.push(command);
      return true;
    }

    function redo() {
      var command = redoStack.pop();
      if (!command) return false;
      command.redo();
      undoStack.push(command);
      return true;
    }

    function clear() {
      undoStack.length = 0;
      redoStack.length = 0;
    }

    return { push: push, undo: undo, redo: redo, clear: clear };
  };
})();
