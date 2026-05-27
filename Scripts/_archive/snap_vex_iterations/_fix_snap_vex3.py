"""Replace BLD_SNAP_VEX: centroid from Y=0 xyzdist, two-pass refinement."""
from pathlib import Path

path = Path('D:/VirtualCity/Scripts/_recook_new_area.py')
c = path.read_text(encoding='utf-8')

OLD_START = 'BLD_SNAP_VEX = """'
OLD_END   = '"""\nsnap_bld = hou.node'

i0 = c.find(OLD_START)
i1 = c.find(OLD_END)
if i0 < 0 or i1 < 0:
    print('block not found'); exit()

NEW_VEX = r'''BLD_SNAP_VEX = """
// snap_bld_to_terrain v3: 质心两步精化 xyzdist
//   Step1: 从 Y=0 查询质心 -> 近海/平原建筑直接命中正下方
//   Step2: 从 Step1 结果 Y 再查一次 -> 坡地建筑消除残差
//   下沉 0.2m 消除底部可见缝隙
int verts[] = primvertices(0, @primnum);
int n = len(verts);

// 质心 XZ
vector ctr = {0,0,0};
foreach(int v; verts) { ctr += point(0, "P", vertexpoint(0, v)); }
ctr /= n;

// Step 1: 从 Y=0 查询（低位点 -> 正下方地形最近）
vector q1 = set(ctr.x, 0.0, ctr.z);
int hp1; vector uvw1;
xyzdist(1, q1, hp1, uvw1);
vector tp1 = primuv(1, "P", hp1, uvw1);

// Step 2: 从 Step1 高度再查一次（消除坡面偏差）
vector q2 = set(ctr.x, tp1.y, ctr.z);
int hp2; vector uvw2;
xyzdist(1, q2, hp2, uvw2);
vector tp2 = primuv(1, "P", hp2, uvw2);

float base_y = tp2.y - 0.2;

// 所有顶点统一到 base_y
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
print('BLD_SNAP_VEX updated to two-pass centroid xyzdist')
