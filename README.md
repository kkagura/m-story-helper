# Maple Vision Lab

Windows 本地视觉识别与离线自动化研究项目。浏览器负责选择共享窗口，Python 负责画面接收、识别及任务引擎；详细设计见 [技术方案.md](技术方案.md)，进度见 [todo.md](todo.md)。

## 当前实现

这是 P0 项目骨架，提供：

- Python 服务入口、JSON 配置、控制台日志和共享 EngineService 生命周期。
- `GET /api/health`、`GET /api/status` 与 `/docs`。
- Vue3 状态页面，显示真实 API 返回的服务连接、引擎运行时间与前端构建状态。
- 开发时 Vite 代理 API；构建后由 FastAPI 托管 `web/dist`。
- HTTP Host/Origin 限制和基础后端测试用例。

窗口共享、WebRTC、识别、规划插件、输入控制尚未接入。状态中的能力字段均为 `false`；服务健康不代表视频链路已完成。

## 开发环境与验证状态

代码文件由虚拟机中的 Codex 编辑，依赖安装、构建、服务启动及 Windows 验证在宿主机执行。虚拟机与宿主机共享源码；虚拟机的工具版本和检查结果不能代表宿主机。不要在两侧同时安装或运行同一个 `.venv`/`node_modules`。

本次只完成文件级检查，尚未在宿主机安装依赖、运行测试、构建前端或启动服务。以下步骤以 Windows PowerShell 为例，在宿主机的项目根目录执行。

建议 Python 3.12；当前包要求 Python ≥3.12。前端采用 Vite 7，需要 Node.js 20.19+（20.x）或 22.12+，与 [Vite 文档](https://vite.dev/guide/) 的运行要求相符；使用宿主机已有的 pnpm。具体 Python/pnpm 版本以你提供的宿主机结果为准。

## 1. 确认宿主机环境

```powershell
py -0p
node --version
pnpm --version
```

如果没有 `py` 启动器，改用 `python --version`，并确认对应解释器满足要求。命令不可用或版本不符时，将结果反馈后再调整安装步骤。

已收到宿主机反馈：Node.js 20.19.0、pnpm 10.34.1；Python 启动器目前列出 3.9 和 2.7，需要先安装 Python 3.12 或其他满足项目要求的版本。以下示例仍按 3.12 执行。每行是一条独立命令，执行成功后再运行下一行，不要将多个命令粘成一行。

## 2. 安装 Python 依赖

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

命令直接使用虚拟环境解释器，不要求执行 PowerShell 激活脚本。已有适用虚拟环境时复用即可；也可以用明确的 Python 路径替代 `py -3.12`。

核心依赖只有 FastAPI、Pydantic 和 Uvicorn；aiortc、PyAV、OpenCV 在对应功能开发时再加入。依赖清单目前为版本范围，宿主机验证后再固定实际版本。

## 3. 启动后端

```powershell
.\.venv\Scripts\python.exe main.py serve
```

默认地址：`http://127.0.0.1:8765`。可访问 `/docs`、`/api/health`、`/api/status`。前端尚未构建时，根页面显示构建提示，这是骨架的正常状态。按 `Ctrl+C` 停止服务。

也可使用虚拟环境中的安装入口：

```powershell
.\.venv\Scripts\maple-vision.exe serve --config configs/default.json
```

配置在 [configs/default.json](configs/default.json)。默认配置与 `web/dist` 相对源码根目录定位；显式传入的相对配置路径相对当前工作目录。CLI 支持 `--host`（仅回环地址）和 `--port` 覆盖，配置错误时明确退出。当前为源码 checkout 开发方式，安装包资源布局与 EXE 发布在 P5 验证。

### 使用 VS Code 调试后端

在宿主机 VS Code 中打开整个项目根目录 `E:\wang\m-story-helper`，安装 Microsoft 的 Python 和 Python Debugger 扩展；[扩展推荐](.vscode/extensions.json) 已写入项目。[调试配置](.vscode/launch.json) 使用 `debugpy`，配置方式参考 [VS Code 官方文档](https://code.visualstudio.com/docs/python/debugging)。

1. 确认宿主机 `.venv\Scripts\python.exe` 已安装项目依赖，并停止占用 8765 端口的手动后端进程。
2. 打开“运行和调试”（`Ctrl+Shift+D`），选择“后端：Maple Vision Lab”，按 `F5`。
3. 配置直接使用项目 `.venv` 的解释器，以根目录为工作目录启动 `main.py serve --config configs/default.json`；日志显示在集成终端。
4. 在 `app/api/server.py` 的 health/status 函数内设置断点，访问 `/api/health` 或刷新前端状态即可触发。调试暂停期间前端请求可能超时。
5. 点击停止按钮结束调试；修改 Python 代码后重新启动调试。本配置不启用自动重载，也不额外启动另一个后端进程。

前端仍在宿主机终端运行 `pnpm --dir web dev`，访问 `http://127.0.0.1:5173`，无需先 build。调试配置为 Windows 宿主机路径，不应在虚拟机/Remote SSH 窗口中使用。VS Code 扩展启动调试时提供 debugpy，无需为此修改项目运行依赖。

## 4. 启动前端开发服务器

保持后端运行，在第二个 PowerShell 终端执行：

```powershell
pnpm --dir web install
pnpm --dir web dev
```

打开 `http://127.0.0.1:5173`。页面使用相对 `/api` 路径，Vite 转发到 `http://127.0.0.1:8765`，不需要开放跨域访问。首次加载或点击“刷新状态”时请求 API，不持续轮询。

若修改后端端口，可复制 `web/.env.example` 为 `web/.env.local`，修改 `MAPLE_BACKEND_URL` 后重启 Vite。若修改前端端口，同步 `vite.config.ts` 和后端配置的 `dev_frontend_port`；固定端口被占用时先解决占用，不自动跳到另一端口。

安装后生成的 `web/pnpm-lock.yaml` 应保留并纳入版本管理。后续安装可在该锁文件验证后使用 `pnpm --dir web install --frozen-lockfile`。

## 5. 构建并由后端托管

```powershell
pnpm --dir web build
```

构建包含 TypeScript 类型检查，产物写入 `web/dist`。停止并重新启动后端，再打开 `http://127.0.0.1:8765`。后端启动时决定是否挂载静态资源，构建后必须重启；部署无需运行 Vite。当前是单页面入口，未接入前端路由。

## 6. 宿主机检查与反馈

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app main.py tests
pnpm --dir web typecheck
pnpm --dir web build
```

后端运行时，在另一终端检查接口：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/api/status | ConvertTo-Json -Depth 5
```

预期健康状态为 `ok`，引擎为 `idle`，所有能力为 `false`；构建并重启后 `web_ui_ready` 为 `true`。页面应显示“已连接”和“空闲”。后端未启动时应显示连接失败，不能保留旧状态为成功。

请反馈环境版本、安装/检查命令结果、两个接口 JSON 和页面连接状态。失败时提供完整错误输出；无需提供凭据或整个依赖目录。只有宿主机验证通过后，才将对应运行验收条目标记完成。

## 目录

```text
app/
  cli.py              服务启动与配置入口
  config.py           配置校验和资源路径
  engine.py           核心服务生命周期及能力状态
  api/server.py       HTTP 接口与静态资源托管
configs/default.json  默认本地配置
web/                  Vue3/Vite/TypeScript 状态页面
tests/test_server.py  API、生命周期、托管与访问限制检查
main.py               源码启动入口
```

开发与交付须遵循 [AGENTS.md](AGENTS.md)，同步待办与技术方案。
