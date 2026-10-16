# cc-vid-scenes

本地视频素材管理 + 音乐卡点视频自动编排工具（Web 管理界面）。
产品文档见 [docs/PRODUCT.md](docs/PRODUCT.md)，阶段计划见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 环境规则

- 本项目使用 conda 虚拟环境 `vid-scenes`（Python 3.11，位于 `E:\run\conda_envs\vid-scenes`）。
- 所有 Python 命令（运行、测试、安装依赖）都必须在该环境中执行，例如：
  - `conda run -n vid-scenes python ...`
  - `conda run -n vid-scenes pip install ...`
- Git Bash 的 PATH 里没有 conda，需要用完整路径：`/c/Users/Danny/miniconda3/Scripts/conda.exe`。
- 不要使用系统 Python 或 base 环境，不要新建其他虚拟环境。
- 新增依赖后同步更新 `requirements.txt`。

## 安装

```bash
conda run -n vid-scenes pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
conda run -n vid-scenes pip install -r requirements.txt
conda run -n vid-scenes pip install --no-deps https://github.com/CPJKU/beat_this/archive/main.zip
```

FFmpeg 和 ffprobe 需要在 PATH 中（支持 NVENC 时会自动用硬件编码）。

## 常用命令

- 启动：`conda run -n vid-scenes python -m uvicorn app.main:app --port 8000`
- 测试：`conda run -n vid-scenes python -m pytest -q`

## 约定

- 片段不物理切割原视频，只存入点和出点。
- GPU 任务通过单 worker 任务队列串行执行。
- 时间线 JSON 是编排结果的唯一事实来源，渲染只读它。
- 运行时数据都放在 `data/`（不纳入版本控制）。
