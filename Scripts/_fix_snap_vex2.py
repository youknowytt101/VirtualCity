"""Replace BLD_SNAP_VEX with high-Y xyzdist centroid approach (no intersect)."""
from pathlib import Path

path = Path('D:/VirtualCity/Scripts/_recook_new_area.py')
c = path.read_text(encoding='utf-8')

# Find and replace the BLD_SNAP_VEX block
OLD_START = 'BLD_SNAP_VEX = """'
OLD_END   = '"""\nsnap_bld = hou.node'

i0 = c.find(OLD_START)
i1 = c.find(OLD_END)

if i0 < 0 or i1 < 0:
    print('block not found'); exit()

OLD_BLOCK = c[i0 : i1 + len(OLD_END)]

NEW_VEX = r'''BLD_SNAP_VEX = """
// snap_bld_to_terrain v2: 质心高-Y xyzdist（等效垂直向下命中），下沉 0.2m 消除缝隙
// 修复 v1 的 MAX xyzdist 悬空问题：
//   原因：顶点在 Y=0，xyzdist 3D 最近点优先命中旁边斜坡而非正下方
//   修复：从质心正上方 Y=99999 查询，距离由垂直分量主导 -> 等效向下命中
int verts[] = primvertices(0, @primnum);
int n = len(verts);

// 1. 质心
vector ctr = {0,0,0};
foreach(int v; verts) { ctr += point(0, "P", vertexpoint(0, v)); }
ctr /= n;

// 2. 从质心正上方高处 xyzdist 命中地形
vector query = set(ctr.x, 99999.0, ctr.z);
int hit_prim; vector uvw;
xyzdist(1, query, hit_prim, uvw);
vector hp = primuv(1, "P", hit_prim, uvw);
float base_y = hp.y - 0.2;   // 下沉 0.2m 消除底部可见缝隙

// 3. 所有顶点统一到 base_y
foreach(int v; verts) {
    int pt = vertexpoint(0, v);
    vector p = point(0, "P", pt);
    p.y = base_y;
    setpointattrib(0, "P", pt, p, "set");
}
"""
snap_bld = hou.node'''

c = c[:i0] + NEW_VEX + c[i1 + len(OLD_END):]
path.write_text(c, encoding='utf-8')
print('BLD_SNAP_VEX updated to centroid high-Y xyzdist approach')
