"""
correct_dem_dtm.py — DSM -> DTM 近似修正
==========================================
原理：
  1. 把现有 DEM CSV (x, y, z) 还原成 2D 高程栅格
  2. 用 Overture 建筑轮廓做掩码，标记"建筑格元"
  3. 对建筑格元用周围非建筑格元的 IDW 插值替代
  4. 写回 CSV，供 dem_import SOP 重新使用

用法（独立）:
    uv run python correct_dem_dtm.py [area_id]
或由 set_area.py / _recook_new_area.py 直接 import 调用:
    from correct_dem_dtm import correct_dtm
"""
import json, csv, math, sys, argparse
from pathlib import Path

# ── 依赖检查（仅 numpy，无需 rasterio）────────────────────────────────────────
try:
    import numpy as np
except ImportError:
    print('[dtm] numpy not found, installing...')
    import subprocess
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'numpy'], check=True)
    import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Scripts'))
import vc_paths
from vc_geo import LocalProjector, local_xz_to_houdini_xz


# ── 几何工具 ─────────────────────────────────────────────────────────────────

def _wgs84_to_local(lon, lat, origin_lon, origin_lat,
                    _cache={}):
    """数据域局部坐标 (x, z)，不翻 z。坐标约定集中在 vc_geo.LocalProjector。"""
    key = (origin_lon, origin_lat)
    proj = _cache.get(key)
    if proj is None:
        proj = _cache[key] = LocalProjector(origin_lon, origin_lat)
    return proj.to_local(lon, lat)


def _point_in_polygon(px, pz, poly_xz):
    """Ray-casting PIP test. poly_xz: list of (x,z) tuples."""
    n = len(poly_xz)
    inside = False
    j = n - 1
    for i in range(n):
        xi, zi = poly_xz[i]
        xj, zj = poly_xz[j]
        if ((zi > pz) != (zj > pz)) and (px < (xj - xi) * (pz - zi) / (zj - zi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _idw_fill(grid, mask, radius=3, power=2):
    """Fill masked cells using IDW from nearby unmasked cells.

    grid  : 2-D numpy float array (NaN where masked)
    mask  : 2-D bool array  (True = needs filling)
    radius: search radius in grid cells
    power : IDW exponent
    """
    result = grid.copy()
    nrows, ncols = grid.shape

    try:
        from scipy.spatial import cKDTree
        # ── 1. Grid coordinate meshgrid ──
        r_grid, c_grid = np.meshgrid(np.arange(nrows), np.arange(ncols), indexing='ij')

        # ── 2. Locate valid source coordinates and values ──
        valid_mask = ~mask & ~np.isnan(grid)
        if not valid_mask.any():
            return result
        valid_coords = np.column_stack((r_grid[valid_mask], c_grid[valid_mask]))
        valid_values = grid[valid_mask]

        # ── 3. Locate target coordinates to fill ──
        masked_coords = np.column_stack((r_grid[mask], c_grid[mask]))
        if len(masked_coords) == 0:
            return result

        # ── 4. Build spatial tree over valid points ──
        tree = cKDTree(valid_coords)

        # ── 5. Query neighbors within cell radius ──
        k = 12
        dists, indices = tree.query(masked_coords, k=k, distance_upper_bound=radius + 0.1)

        # ── 6. Filter out-of-bounds search values and compute IDW ──
        valid_neighbors = (dists < np.inf)
        safe_indices = np.where(valid_neighbors, indices, 0)
        neighbor_values = valid_values[safe_indices]

        dists[dists == 0] = 1e-6
        weights = 1.0 / (dists ** power)
        weights[~valid_neighbors] = 0.0

        weight_sum = weights.sum(axis=1)
        has_neighbors = weight_sum > 0

        weighted_sum = (weights * neighbor_values).sum(axis=1)
        interpolated = np.zeros(len(masked_coords))
        interpolated[has_neighbors] = weighted_sum[has_neighbors] / weight_sum[has_neighbors]

        # ── 7. Vectorized write back to the result array ──
        mask_rows = masked_coords[:, 0]
        mask_cols = masked_coords[:, 1]
        result[mask_rows[has_neighbors], mask_cols[has_neighbors]] = interpolated[has_neighbors]
        return result

    except ImportError:
        # Fallback to optimized NumPy window loop if SciPy is not available
        rows, cols = np.where(mask)
        dr = np.arange(-radius, radius + 1)
        dc = np.arange(-radius, radius + 1)
        DC, DR = np.meshgrid(dc, dr)
        dist_kernel = np.sqrt(DR**2 + DC**2)
        dist_kernel[radius, radius] = 1e-6  # avoid division by zero at center
        weight_kernel = 1.0 / (dist_kernel ** power)

        for r, c in zip(rows, cols):
            r0 = max(0, r - radius)
            r1 = min(nrows, r + radius + 1)
            c0 = max(0, c - radius)
            c1 = min(ncols, c + radius + 1)

            patch = grid[r0:r1, c0:c1]
            pmask = mask[r0:r1, c0:c1]
            valid = ~pmask & ~np.isnan(patch)
            if not valid.any():
                continue

            # Get the corresponding sliced weight kernel centered relative to (r, c)
            kr0 = r0 - r + radius
            kr1 = r1 - r + radius
            kc0 = c0 - c + radius
            kc1 = c1 - c + radius
            w = weight_kernel[kr0:kr1, kc0:kc1] * valid

            w_sum = w.sum()
            if w_sum > 0:
                result[r, c] = (w * patch).sum() / w_sum

        return result


# ── 主修正函数 ────────────────────────────────────────────────────────────────

def correct_dtm(area_cfg: dict, verbose: bool = True) -> bool:
    """
    area_cfg: dict loaded from active_area.json.
    Returns True if correction was applied, False if skipped.
    """
    dem_csv_path    = vc_paths.resolve_project_path(area_cfg['dem_csv'])
    buildings_path  = vc_paths.resolve_project_path(area_cfg['buildings_file'])
    origin_lon      = area_cfg['origin_lon']
    origin_lat      = area_cfg['origin_lat']

    if not dem_csv_path.exists():
        print('[dtm] DEM CSV not found, skip.')
        return False
    if not buildings_path.exists():
        print('[dtm] Buildings GeoJSON not found, skip.')
        return False

    # ── 1. 读取 DEM CSV → numpy 数组 ──────────────────────────────────────────
    with open(dem_csv_path, encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)           # ['x', 'y', 'z'] or ['x', 'y', 'z', 'row', 'col']
        raw_rows = list(reader)
    pts = [(float(r[0]), float(r[1]), float(r[2])) for r in raw_rows]
    extra_cols = [r[3:] for r in raw_rows]  # preserve row, col etc.

    xs  = sorted(set(round(p[0], 2) for p in pts))
    zs  = sorted(set(round(p[2], 2) for p in pts))
    nx, nz = len(xs), len(zs)
    if verbose:
        print(f'[dtm] DEM grid: {nx} x {nz} = {nx*nz} cells  (actual={len(pts)})')

    x_idx = {v: i for i, v in enumerate(xs)}
    z_idx = {v: i for i, v in enumerate(zs)}

    elev_grid = np.full((nz, nx), np.nan)
    for px, py, pz in pts:
        xi = x_idx.get(round(px, 2))
        zi = z_idx.get(round(pz, 2))
        if xi is not None and zi is not None:
            elev_grid[zi, xi] = py

    # ── 2. 读取建筑轮廓 → 本地坐标多边形列表 ────────────────────────────────
    with open(buildings_path, encoding='utf-8') as f:
        fc = json.load(f)

    polys = []
    for feat in fc['features']:
        geom = feat.get('geometry')
        if geom is None:
            continue
        gtype = geom.get('type')
        if gtype == 'Polygon':
            poly_list = [geom['coordinates']]
        elif gtype == 'MultiPolygon':
            poly_list = geom['coordinates']
        else:
            continue

        for poly in poly_list:
            if not poly:
                continue
            ring = poly[0]
            local = []
            for coord in ring:
                lx, lz = _wgs84_to_local(coord[0], coord[1], origin_lon, origin_lat)
                local.append(local_xz_to_houdini_xz(lx, lz))   # 唯一 z 翻转处集中在 vc_geo
            if len(local) >= 3:
                polys.append(local)

    if verbose:
        print(f'[dtm] Building polygons loaded: {len(polys)}')

    # ── 3. 建筑格元掩码 ───────────────────────────────────────────────────────
    bld_mask = np.zeros((nz, nx), dtype=bool)
    cell_w = (xs[-1] - xs[0]) / max(nx - 1, 1)
    cell_h = (zs[-1] - zs[0]) / max(nz - 1, 1)

    for poly in polys:
        # AABB pre-filter
        poly_xs = [p[0] for p in poly]
        poly_zs = [p[1] for p in poly]
        bmin_x, bmax_x = min(poly_xs), max(poly_xs)
        bmin_z, bmax_z = min(poly_zs), max(poly_zs)

        # Grid index range to check
        xi0 = max(0, int((bmin_x - xs[0]) / cell_w) - 1)
        xi1 = min(nx, int((bmax_x - xs[0]) / cell_w) + 2)
        zi0 = max(0, int((bmin_z - zs[0]) / cell_h) - 1)
        zi1 = min(nz, int((bmax_z - zs[0]) / cell_h) + 2)

        for zi in range(zi0, zi1):
            for xi in range(xi0, xi1):
                cx, cz = xs[xi], zs[zi]
                if _point_in_polygon(cx, cz, poly):
                    bld_mask[zi, xi] = True

    n_masked = bld_mask.sum()
    pct = 100.0 * n_masked / (nx * nz)
    if verbose:
        print(f'[dtm] Building-masked cells: {n_masked} ({pct:.1f}% of grid)')

    if n_masked == 0:
        print('[dtm] No cells masked, nothing to correct.')
        return False

    # ── 4. IDW 插值填充建筑格元 ───────────────────────────────────────────────
    elev_before = elev_grid[bld_mask].copy()
    elev_corrected = _idw_fill(elev_grid, bld_mask, radius=4, power=2)

    elev_after  = elev_corrected[bld_mask]
    delta_mean  = float(np.nanmean(elev_before - elev_after))
    delta_max   = float(np.nanmax(elev_before - elev_after))
    if verbose:
        print(f'[dtm] Elevation correction: mean={delta_mean:+.1f}m  max={delta_max:+.1f}m')

    # ── 5. 写回 CSV (原子写入) ────────────────────────────────────────────────
    tmp_path = dem_csv_path.with_suffix('.tmp')
    with open(tmp_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for i, (px, py, pz) in enumerate(pts):
            xi = x_idx.get(round(px, 2))
            zi = z_idx.get(round(pz, 2))
            if xi is not None and zi is not None and not np.isnan(elev_corrected[zi, xi]):
                new_y = float(elev_corrected[zi, xi])
            else:
                new_y = py
            writer.writerow([f'{px:.2f}', f'{new_y:.2f}', f'{pz:.2f}'] + extra_cols[i])

    tmp_path.replace(dem_csv_path)
    if verbose:
        print(f'[dtm] Corrected DEM written: {dem_csv_path.name}')

    return True


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description='DSM -> DTM correction via building mask')
    ap.add_argument('area_id', nargs='?', default=None, help='Area ID (default: active_area)')
    args = ap.parse_args()

    cfg = vc_paths.load_active_area()
    if args.area_id and cfg.get('area_id') != args.area_id:
        print(f'[dtm] Warning: active area is {cfg.get("area_id")}, not {args.area_id}')

    correct_dtm(cfg, verbose=True)


if __name__ == '__main__':
    main()
