@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title TRAWL - Cloudflare Bypass

echo ========================================
echo   TRAWL - Cloudflare Bypass Service
echo   Windows Portable Edition
echo ========================================
echo.

cd /d "%~dp0"

rem 定位 Bun：兼容 bun\bun.exe 与 bun\bun-windows-x64\bun.exe 两种嵌套结构
set "BUN_EXE="
if exist "bun\bun.exe" (
    set "BUN_EXE=bun\bun.exe"
) else (
    for /d %%D in ("bun\bun-windows-*") do (
        if exist "%%D\bun.exe" set "BUN_EXE=%%D\bun.exe"
    )
)
if not defined BUN_EXE (
    echo [ERROR] 未找到 Bun，请先运行 download-bun.bat
    pause
    exit /b 1
)
echo [INFO] Bun: %BUN_EXE%

rem 决定运行哪份源码：优先包根自带源码（打包时已应用补丁、依赖已就位、完全离线）；
rem src\ 在线克隆副本仅作兜底（包根无源码的裸部署场景），避免首启强依赖外网且版本漂移
set "SRC_DIR="
if exist "apps\api\src\index.ts" (
    set "SRC_DIR=."
    echo [INFO] 使用便携包自带源码
) else if exist "src\apps\api\src\index.ts" (
    set "SRC_DIR=src"
    echo [INFO] 使用 src\ 目录源码
) else (
    echo [INFO] 未发现源码，正在克隆上游仓库到 src\ ...
    git clone --depth 1 https://github.com/germondai/trawl.git src
    if errorlevel 1 (
        echo [ERROR] 克隆失败，请检查网络连接
        pause
        exit /b 1
    )
    set "SRC_DIR=src"
)

rem 对 src\ 克隆副本兜底应用 MDCx 兼容补丁（提升 Tier3/4 页面加载超时上限，改善挑战页稳定性）
rem 包根自带源码在打包阶段已应用过补丁，无需重复处理
if "%SRC_DIR%"=="src" if exist "trawl-goto-timeout.patch" (
    cd /d "%~dp0src"
    git apply --check ..\trawl-goto-timeout.patch >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] 应用 TRAWL goto 超时补丁...
        git apply ..\trawl-goto-timeout.patch
        if errorlevel 1 echo [WARN] 补丁应用失败，继续以原版运行
    ) else (
        echo [INFO] 补丁已应用或无法应用，跳过
    )
    cd /d "%~dp0"
)

rem 校验/安装依赖：必须在所运行源码的目录内执行，bun 按当前目录的 package.json/bun.lock 安装，
rem 跑错目录等于没装；每次启动做一次幂等校验（已是最新时毫秒级），既兜底依赖缺失，也吸收克隆副本的上游依赖变更
if exist "%SRC_DIR%\node_modules" (
    echo [INFO] 校验依赖...
) else (
    echo [INFO] 正在安装依赖，请稍候（首次较慢）...
)
pushd "%~dp0%SRC_DIR%"
"%BUN_EXE%" install --frozen-lockfile
if errorlevel 1 (
    echo [WARN] frozen lockfile 安装失败，尝试普通安装...
    "%BUN_EXE%" install
)
set "INSTALL_ERR=%errorlevel%"
popd
if not "%INSTALL_ERR%"=="0" (
    echo [ERROR] 依赖安装失败，请检查网络后重试
    pause
    exit /b 1
)

rem 设置环境变量
set MITM_PROXY_ENABLED=false
set PORT=8191
rem 浏览器池默认 2（稳定性/内存折中，用户可改 .env 的 BROWSER_POOL_SIZE）
set BROWSER_POOL_SIZE=2
rem 让 camoufox-js 直接使用便携包内自带的 Camoufox 浏览器，避免在线下载
set CAMOUFOX_INSTALL_DIR=%~dp0.cache\camoufox

rem 内置 Redis：便携包自带，自动启动用于 TRAWL 会话缓存（Tier 2 fast-path）
rem 定位 redis-server.exe：兼容 redis\redis-server.exe 与 redis\Redis-*\redis-server.exe 两种嵌套结构
set "REDIS_EXE="
set REDIS_URL=
if exist "redis\redis-server.exe" (
    set "REDIS_EXE=redis\redis-server.exe"
) else (
    for /d %%D in ("redis\Redis-*") do (
        if exist "%%D\redis-server.exe" set "REDIS_EXE=%%D\redis-server.exe"
    )
)
if defined REDIS_EXE (
    echo [INFO] 检测到内置 Redis: %REDIS_EXE%，正在启动...
    start "TRAWL-Redis" /min "%~dp0%REDIS_EXE%" --port 6380 --save "" --appendonly no
    if not errorlevel 1 (
        set REDIS_URL=redis://127.0.0.1:6380
        echo [INFO] Redis 已启动，TRAWL 会话缓存已启用
    )
) else (
    echo [INFO] 未发现内置 Redis，TRAWL 将以无缓存模式运行
)
if defined REDIS_URL set REDIS_URL=redis://127.0.0.1:6380

echo.
echo [INFO] 服务启动中...
echo [INFO] API 地址: http://localhost:%PORT%
echo [INFO] 健康检查: http://localhost:%PORT%/health
echo.
echo [提示] 按 Ctrl+C 停止服务
echo.

rem 启动服务（cwd 保持包根，bun 从包根 .env 读配置）
"%BUN_EXE%" run "%SRC_DIR%\apps\api\src\index.ts"

if errorlevel 1 (
    echo.
    echo [ERROR] 服务启动失败
    pause
)
