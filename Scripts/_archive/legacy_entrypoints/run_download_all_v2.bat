@echo off
setlocal
REM VirtualCity - 一键下载 v2 区域全套数据（OSM + 建筑高度 + DEM）
REM 区域: pattaya_sai6_mvp_v2  bbox: 100.860/12.916/100.888/12.944 (3km x 3km)

set "SCRIPTS=%~dp0"
set "MIRROR=https://mirrors.aliyun.com/pypi/simple/"

pushd "%SCRIPTS%" || exit /b 1

echo ============================================
echo  VirtualCity 数据下载 v2 (3km x 3km)
echo ============================================
echo.

echo [1/3] 下载 OSM 数据...
uv run python download_osm.py pattaya_sai6_mvp_v2
if errorlevel 1 (echo [错误] OSM 下载失败 & popd & pause & exit /b 1)
echo.

echo [2/3] 下载建筑高度数据 (Google Open Buildings 2.5D)...
uv run --with earthengine-api --index-url %MIRROR% python download_building_heights.py --area pattaya_sai6_mvp_v2
if errorlevel 1 (echo [错误] 建筑高度下载失败 & popd & pause & exit /b 1)
echo.

echo [3/3] 下载 DEM 地形数据 (SRTM 30m)...
uv run --with earthengine-api --index-url %MIRROR% python download_dem.py pattaya_sai6_mvp_v2
if errorlevel 1 (echo [错误] DEM 下载失败 & popd & pause & exit /b 1)
echo.

echo ============================================
echo  全部完成！
echo  OSM:  RawData\OSM\pattaya_sai6_mvp_v2_osm_v001.osm
echo  建筑: RawData\Overture\pattaya_sai6_mvp_v2_buildings_height_v001.geojson
echo  DEM:  RawData\DEM\pattaya_sai6_mvp_v2_dem_v001.tif
echo ============================================
popd
pause
