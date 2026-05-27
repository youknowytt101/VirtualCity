"""
VirtualCity — Overture Maps 建筑下载脚本（混合模式）
===========================================
建筑轮廓来自 Overture Maps，高度自动从 Google Open Buildings 填充。
当 Overture 高度覆盖率 < 80% 时，追加下载 Google Open Buildings
并通过 STRtree 空间 join 将高度分配给每栈建筑。

用法:
    uv run python download_overture_buildings.py \\
        --bbox west south east north --output path/to/output.geojson

最终效果: Overture 轮廓精度 + Google 高度覆盖率
"""
import argparse, json, subprocess, sys, tempfile
from pathlib import Path

DEFAULT_HEIGHT   = 0.0   # Overture 和 Google 均未知时的属层备用默认
FLOOR_HEIGHT     = 3.5   # num_floors → height 换算系数
HEIGHT_THRESHOLD = 0.80  # Overture 覆盖率低于此就执行 Google 高度 join
JOIN_MAX_DIST    = 50.0   # 空间 join 最大匹配距离（米）


def _fetch_overture(bbox):
    """Return list of features with geometry (shapely) + properties."""
    import overturemaps
    from shapely import from_wkb
    from shapely.geometry import mapping

    west, south, east, north = bbox
    features = []
    reader = overturemaps.record_batch_reader('building', bbox=(west, south, east, north))
    for batch in reader:
        d = batch.to_pydict()
        n = len(d.get('geometry', []))
        for i in range(n):
            wkb = d['geometry'][i]
            if wkb is None:
                continue
            try:
                geom = from_wkb(bytes(wkb))
                geom_dict = mapping(geom)
            except Exception:
                continue

            h = d.get('height', [None] * n)[i]
            floors = d.get('num_floors', [None] * n)[i]
            if h is not None and h > 0:
                height, real = float(h), True
            elif floors is not None and floors > 0:
                height, real = float(floors) * FLOOR_HEIGHT, True
            else:
                height, real = DEFAULT_HEIGHT, False

            # Overture schema: 顶层是 'subtype'（residential/commercial/...），
            # 'class' 是更细分类（apartments/office/...）。两者皆可缺。
            # 优先 subtype，其次 class，最后 'building' 兜底。
            subtype_arr = d.get('subtype', [None] * n)
            class_arr   = d.get('class',   [None] * n)
            sub_v = subtype_arr[i] if i < len(subtype_arr) else None
            cls_v = class_arr[i]   if i < len(class_arr)   else None
            bld_class = sub_v or cls_v or 'building'

            features.append({
                'geom':    geom,
                'geom_dict': geom_dict,
                'height':  height,
                'real':    real,
                'class':   bld_class,
            })
    return features


def _fetch_google_heights(bbox, scripts_dir):
    """下载 Google Open Buildings 到临时文件，返回 features 列表。"""
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix='.geojson', delete=False)
    tmp.close()
    cmd = [
        'uv', 'run', 'python', 'download_building_heights.py',
        '--bbox', str(bbox[0]), str(bbox[1]), str(bbox[2]), str(bbox[3]),
        '--output', tmp.name,
    ]
    r = subprocess.run(cmd, cwd=str(scripts_dir), capture_output=False)
    if r.returncode != 0 or not Path(tmp.name).exists():
        print('  ⚠ Google Open Buildings 下载失败，高度将使用 Overture 默认值')
        return []
    with open(tmp.name, encoding='utf-8') as f:
        fc = json.load(f)
    Path(tmp.name).unlink(missing_ok=True)
    return fc.get('features', [])


def _spatial_join_heights(overture_feats, google_feats):
    """用 STRtree 将 Google 高度分配给没有真实高度的 Overture 建筑。"""
    from shapely.geometry import shape
    from shapely import STRtree

    if not google_feats:
        return

    # 构建 Google 建筑中心点索引
    g_geoms  = [shape(f['geometry']).centroid for f in google_feats]
    g_heights = [float(f['properties'].get('height') or DEFAULT_HEIGHT)
                 for f in google_feats]
    tree = STRtree(g_geoms)

    joined = 0
    candidates = sum(1 for f in overture_feats if not f['real'])
    for feat in overture_feats:
        if feat['real']:
            continue  # 已有真实高度，跳过
        centroid = feat['geom'].centroid
        idx = tree.nearest(centroid)
        dist = centroid.distance(g_geoms[idx])
        # distance 是度，转为米（简化：1度 ≈ 111319m，对亚热带小区域足够）
        dist_m = dist * 111319.0
        if dist_m <= JOIN_MAX_DIST:
            feat['height'] = g_heights[idx]
            feat['real']   = True
            joined += 1
    print(f'  空间 join: {joined}/{candidates} 栋无高度建筑匹配到 Google 高度')


def download(bbox, output_path, scripts_dir=None):
    """主流程: Overture 轮廓 + 按需 Google 高度 join。"""
    try:
        import overturemaps
    except ImportError:
        print('  ❌ 缺少 overturemaps，请运行: uv add overturemaps', file=sys.stderr)
        sys.exit(1)
    try:
        from shapely import from_wkb  # noqa 测试 shapely 可用
    except ImportError:
        print('  ❌ 缺少 shapely，请运行: uv add shapely', file=sys.stderr)
        sys.exit(1)

    print(f'  [Overture] 下载建筑轮廓...')
    feats = _fetch_overture(bbox)
    total = len(feats)
    if total == 0:
        print('  ⚠ Overture 该区域无建筑数据')

    real_count = sum(1 for f in feats if f['real'])
    coverage   = real_count / total if total else 0
    print(f'  [Overture] {total} 栈建筑，高度覆盖率 {coverage*100:.0f}%')

    if coverage < HEIGHT_THRESHOLD and scripts_dir:
        print(f'  高度覆盖率 < {HEIGHT_THRESHOLD*100:.0f}%，自动获取 Google Open Buildings 高度...')
        google_feats = _fetch_google_heights(bbox, scripts_dir)
        if google_feats:
            print(f'  [Google] 获取 {len(google_feats)} 栄建筑高度')
            _spatial_join_heights(feats, google_feats)

    # 输出 GeoJSON
    out_features = []
    final_real = 0
    for f in feats:
        out_features.append({
            'type': 'Feature',
            'geometry': f['geom_dict'],
            'properties': {
                'height': f['height'],
                'class':  f['class'],
                'source': 'overture',
            }
        })
        if f['real']:
            final_real += 1

    fc = {'type': 'FeatureCollection', 'features': out_features}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as fp:
        json.dump(fc, fp, ensure_ascii=False)

    return total, final_real, len(out_features)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bbox',   nargs=4, type=float, required=True,
                    metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'))
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    scripts_dir = Path(__file__).parent
    total, with_h, saved = download(args.bbox, args.output, scripts_dir)
    pct = with_h / saved * 100 if saved else 0
    print(f'  Saved {saved} 栈建筑, {with_h} 有真实高度 ({pct:.0f}%)')
    print(f'  → {args.output}')


if __name__ == '__main__':
    main()
