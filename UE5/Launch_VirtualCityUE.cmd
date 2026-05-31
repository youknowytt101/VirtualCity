@echo off
setlocal

set "UE-LocalDataCachePath=G:\UE5Cache\DerivedDataCache"
set "UE-SharedDataCachePath=None"

start "" "C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor.exe" "%~dp0VirtualCityUE\VirtualCityUE.uproject" -ddc=InstalledNoZenLocalFallback -LocalDataCachePath="G:\UE5Cache\DerivedDataCache"

endlocal
