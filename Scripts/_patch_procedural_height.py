"""P0 patch: update procedural_height VEX to also handle height_m <= 0."""
import rpyc

NEW_VEX = r"""// P0: 推算高度的触发条件:
//   1. height_m ~= 10.0  -> OSM/Overture 默认值，没有真实数据
//   2. height_m <= 0      -> 明确缺失或数据错误
int needs_estimate = (abs(f@height_m - 10.0) < 0.1) || (f@height_m <= 0);
if (!needs_estimate) return;

// 用 Shoelace 公式计算建筑底面积（XZ 平面）
int pts[] = primpoints(0, @primnum);
int n = len(pts);
float area = 0;
for (int i = 0; i < n; i++) {
    vector p0 = point(0, "P", pts[i]);
    vector p1 = point(0, "P", pts[(i+1)%n]);
    area += p0.x * p1.z - p1.x * p0.z;
}
area = abs(area) * 0.5;

// 基于面积推算基础楼层数（针对 Pattaya 低密度分布）
float base_floors;
if      (area < 60)   base_floors = 1;
else if (area < 150)  base_floors = 2;
else if (area < 400)  base_floors = 3;
else if (area < 1000) base_floors = 4;
else if (area < 3000) base_floors = 6;
else                  base_floors = 8;

// 引入位置相关的随机扰动，避免同面积建筑等高
vector ctr = {0,0,0};
for (int i = 0; i < n; i++) ctr += point(0,"P",pts[i]);
ctr /= n;
float noise_val = fit(noise(ctr * 0.003), 0, 1, -1.5, 1.5);
float floors = clamp(base_floors + noise_val, 1, 15);

f@height_m = floors * 3.5;
"""

conn = rpyc.classic.connect('localhost', 18811)
hou = conn.modules.hou

n = hou.node('/obj/pattaya_osm/procedural_height')
n.parm('snippet').set(NEW_VEX)
n.cook(force=True)

g = n.geometry()
heights = [p.attribValue('height_m') for p in g.prims()]
zero  = sum(1 for h in heights if h <= 0)
low   = sum(1 for h in heights if 0 < h <= 5)
med   = sum(1 for h in heights if 5 < h <= 30)
high  = sum(1 for h in heights if h > 30)
print(f'total: {len(heights)}  zero/negative: {zero}  1-5m: {low}  5-30m: {med}  >30m: {high}')
print(f'errors: {n.errors()}')

hou.hipFile.save()
print('HIP saved')
conn.close()
