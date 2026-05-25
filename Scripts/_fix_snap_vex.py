"""Replace BLD_SNAP_VEX in _recook_new_area.py with raycast-based approach."""
from pathlib import Path

path = Path('D:/VirtualCity/Scripts/_recook_new_area.py')
c = path.read_text(encoding='utf-8')

OLD_VEX = '''BLD_SNAP_VEX = """
// 对每栋楼逐顶点查询地形高度，取 MAX 作为底面 Y
// 防止坡面上坡侧顶点被地形埋没（H-011）
float max_y = -1e9;
int verts[] = primvertices(0, @primnum);
foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);
    int hit_prim;
    vector uvw;
    xyzdist(1, p, hit_prim, uvw);
    vector tp = primuv(1, "P", hit_prim, uvw);
    if (tp.y > max_y) max_y = tp.y;
}
foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);
    p.y = max_y;
    setpointattrib(0, "P", pt, p, "set");
}
"""'''

NEW_VEX = r'''BLD_SNAP_VEX = """
// snap_bld_to_terrain v2: 垂直向下 raycast 取质心地形高度，下沉 0.2m 消除缝隙
// 修复原 xyzdist MAX 方案导致的建筑悬空问题：
//   xyzdist 是 3D 最近距离，顶点在 Y=0 时会优先命中旁边斜坡而非正下方
int verts[] = primvertices(0, @primnum);
int n = len(verts);

// 1. 计算建筑底面质心
vector ctr = {0,0,0};
foreach(int v; verts) {
    ctr += point(0, "P", vertexpoint(0, v));
}
ctr /= n;

// 2. 从质心正上方垂直向下射线命中地形
vector ray_orig = set(ctr.x, 99999.0, ctr.z);
vector ray_dir  = {0, -1, 0};
vector hit_pos;
vector uvw;
int hit = intersect(1, ray_orig, ray_dir * 199999.0, hit_pos, uvw);

float base_y;
if (hit >= 0) {
    base_y = hit_pos.y - 0.2;   // 下沉 0.2m 消除缝隙
} else {
    // fallback: xyzdist（建筑在地形范围外时）
    int hp;
    xyzdist(1, ctr, hp, uvw);
    base_y = primuv(1, "P", hp, uvw).y - 0.2;
}

// 3. 所有顶点统一到 base_y
foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);
    p.y = base_y;
    setpointattrib(0, "P", pt, p, "set");
}
"""'''

if OLD_VEX in c:
    c = c.replace(OLD_VEX, NEW_VEX, 1)
    path.write_text(c, encoding='utf-8')
    print('BLD_SNAP_VEX replaced with raycast approach')
else:
    print('pattern not found')
