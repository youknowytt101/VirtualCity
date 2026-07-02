// Domain: game-workbench / collision
// Owns: the BVH-accelerated static collider (three-mesh-bvh) built from scene
//       geometry, and the capsule-vs-collider push-out used by play mode's
//       movement/camera. Ported from hh-hang/three-player-controller's
//       utils/capsuleCollision.ts + playerController.ts buildStaticCollider,
//       adapted from that project's Y-up world to this project's Z-up world.
// AI handoff: For "walked through a wall" or "camera clips through geometry"
//             bugs, start here. The collider mesh itself is built in
//             game_workbench.js (buildOrRefreshPlayCollider, owns scene
//             access); gw_play.js consumes it for movement + camera.
(function() {
  'use strict';

  var GW = window.VC_GW || (window.VC_GW = {});
  var safeThree = GW.safeThree;
  var depsPromise = null;

  function loadCollisionDeps() {
    if (!depsPromise) {
      depsPromise = Promise.all([
        import("three-mesh-bvh"),
        import("/static/utils/BufferGeometryUtils.js")
      ]).then(function(mods) {
        return { bvh: mods[0], geomUtils: mods[1] };
      });
    }
    return depsPromise;
  }

  // Collision only needs vertex positions -- dropping normal/uv/color/skin
  // attributes means every source mesh reduces to the same attribute set
  // (just "position"), so BufferGeometryUtils.mergeBufferGeometries never
  // trips on mismatched attributes across whitebox terrain/buildings/roads
  // and arbitrary imported GLB props.
  function toPositionOnlyGeometry(geometry) {
    var THREE = safeThree();
    var out = new THREE.BufferGeometry();
    out.setAttribute('position', geometry.getAttribute('position'));
    return out;
  }

  // Builds one merged, BVH-accelerated collider mesh (never added to the
  // visible scene) from every mesh under `candidates` -- mirrors the
  // reference's buildStaticCollider, minus its dynamic-collider/debug-
  // visualizer machinery this project doesn't need. Resolves to null when
  // there's nothing collidable (empty scene), so callers can fall back to
  // simpler per-object raycasting.
  function buildPlayCollider(candidates) {
    var THREE = safeThree();
    if (!THREE || !candidates || !candidates.length) return Promise.resolve(null);
    return loadCollisionDeps().then(function(deps) {
      var collected = [];
      candidates.forEach(function(root) {
        root.updateMatrixWorld(true);
        root.traverse(function(node) {
          if (!node.isMesh || !node.geometry) return;
          if (node.userData && node.userData.pickable === false) return;
          var position = node.geometry.attributes && node.geometry.attributes.position;
          if (!position || !position.count) return;
          var geom = node.geometry.clone();
          geom.applyMatrix4(node.matrixWorld);
          if (geom.index) geom = geom.toNonIndexed();
          collected.push(toPositionOnlyGeometry(geom));
        });
      });
      if (!collected.length) return null;
      var merged = deps.geomUtils.mergeBufferGeometries(collected, false);
      if (!merged) return null;
      merged.boundsTree = new deps.bvh.MeshBVH(merged);
      var colliderMesh = new THREE.Mesh(merged);
      colliderMesh.raycast = deps.bvh.acceleratedRaycast;
      colliderMesh.updateMatrixWorld();
      return colliderMesh;
    });
  }

  // Preallocated scratch objects for applyCapsuleCollision (one set per
  // independent capsule/collider pairing so concurrent calls don't clobber
  // each other's temps).
  function createCollisionTemps() {
    var THREE = safeThree();
    return {
      invMat: new THREE.Matrix4(),
      localSeg: new THREE.Line3(),
      localBox: new THREE.Box3(),
      originalWorldStart: new THREE.Vector3(),
      closestSeg: new THREE.Vector3(),
      closestTri: new THREE.Vector3()
    };
  }

  // Pushes `capsule` (an Object3D; .position is mutated in place) out of any
  // collider triangle closer than capsuleInfo.radius to its segment. Ported
  // from capsuleCollision.ts's applyCapsuleCollision, which is otherwise
  // axis-agnostic (it works in the collider's local space) -- the one change
  // here is computing the position delta from the segment start's own
  // original/corrected world position rather than assuming the segment start
  // sits exactly at the capsule object's local origin (the reference always
  // constructs its capsule that way; this project's player Group origin sits
  // partway up the body, at chest height, so that assumption doesn't hold).
  function applyCapsuleCollision(capsule, capsuleInfo, collider, temps) {
    if (!collider || !collider.geometry || !collider.geometry.boundsTree) return;
    temps.invMat.copy(collider.matrixWorld).invert();
    temps.localSeg.start.copy(capsuleInfo.segment.start).applyMatrix4(capsule.matrixWorld).applyMatrix4(temps.invMat);
    temps.localSeg.end.copy(capsuleInfo.segment.end).applyMatrix4(capsule.matrixWorld).applyMatrix4(temps.invMat);
    temps.originalWorldStart.copy(temps.localSeg.start).applyMatrix4(collider.matrixWorld);

    temps.localBox.makeEmpty();
    temps.localBox.expandByPoint(temps.localSeg.start).expandByPoint(temps.localSeg.end);
    temps.localBox.expandByScalar(capsuleInfo.radius);

    collider.geometry.boundsTree.shapecast({
      intersectsBounds: function(box) { return box.intersectsBox(temps.localBox); },
      intersectsTriangle: function(tri) {
        var distance = tri.closestPointToSegment(temps.localSeg, temps.closestSeg, temps.closestTri);
        if (distance >= capsuleInfo.radius) return;
        var dir = temps.closestTri.clone().sub(temps.closestSeg).normalize();
        temps.localSeg.start.addScaledVector(dir, capsuleInfo.radius - distance);
        temps.localSeg.end.addScaledVector(dir, capsuleInfo.radius - distance);
      }
    });

    var newWorldStart = temps.closestSeg.copy(temps.localSeg.start).applyMatrix4(collider.matrixWorld);
    var delta = temps.closestTri.subVectors(newWorldStart, temps.originalWorldStart);
    var offset = Math.max(0, delta.length() - 1e-5);
    capsule.position.add(delta.normalize().multiplyScalar(offset));
  }

  GW.buildPlayCollider = buildPlayCollider;
  GW.createCollisionTemps = createCollisionTemps;
  GW.applyCapsuleCollision = applyCapsuleCollision;
})();
