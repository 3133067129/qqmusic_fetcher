# Music Fetcher Pro 打包说明（Windows）

## 1. Python 版本要求
- 推荐：`Python 3.11.7 (64-bit)`（已按本项目验证）
- 不建议低于 `3.11`

## 2. 依赖安装命令
在项目根目录执行：

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果还没有虚拟环境：

```bat
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. 打包命令
### 一键方式（推荐）
```bat
build.bat
```

### 手动方式
```bat
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean music_fetcher_pro.spec
```

### 首次验证用过的直连命令（无 spec）
```bat
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name music_fetcher_pro --icon build_assets\app.ico --version-file build_assets\version_info.txt --collect-data ttkthemes --collect-data certifi --collect-submodules yt_dlp --collect-submodules mutagen main_gui.py
```

## 4. 输出目录说明
- `dist\music_fetcher_pro.exe`：最终可执行文件（onefile）
- `build\`：PyInstaller 构建过程文件
- `music_fetcher_pro.spec`：正式打包配置

## 5. 常见错误与解决方法
- `No module named ...`
  - 先确认已执行：`pip install -r requirements.txt`
  - 再执行：`pyinstaller --clean ...`（已在 `build.bat` 内）

- `未检测到 ffmpeg` / 下载时报 ffmpeg 错误
  - 安装 ffmpeg 并加入系统 `PATH`
  - 或把 `ffmpeg.exe`（可选加 `ffprobe.exe`）放到 `exe` 同目录或 `bin\` 目录

- 运行后主题/界面资源缺失
  - 使用本仓库提供的 `music_fetcher_pro.spec` 重打包，不要省略其中 `ttkthemes` 的 datas 收集

- 杀毒软件误报
  - 对 `dist\music_fetcher_pro.exe` 做白名单
  - 尽量在干净环境重新 `--clean` 打包

## 6. exe 运行验证步骤
1. 双击 `dist\music_fetcher_pro.exe`，确认 GUI 能正常打开。
2. 在 GUI 中执行一次“单曲搜索”，确认日志区有实时输出。
3. 选择下载目录后执行一次“下载”，确认生成音频文件。
4. 检查日志文件：
   - 源码运行：`logs\app.log`
   - exe 运行：`%LOCALAPPDATA%\qqmusic2bilibili\logs\app.log`

## 7. 打包策略说明
- 当前采用：`PyInstaller + onefile + --windowed`（GUI 项目关闭控制台）
- 如 onefile 在目标机器被拦截或启动异常，可改为 onedir：

```bat
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir music_fetcher_pro.spec
```

原因：`onedir` 对安全软件和临时解压路径更友好，排障成本更低。
