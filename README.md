# Maple Vision Lab

Windows 本地视觉识别与离线自动化研究项目。浏览器负责选择共享窗口，Python 负责画面接收、识别及任务引擎；详细设计见 [技术方案.md](技术方案.md)，进度见 [todo.md](todo.md)。

## 当前实现

当前包含 P0 视频链路和离线截图识别调试增量，提供：

- Python 服务入口、JSON 配置、控制台日志和共享 EngineService 生命周期。
- `GET /api/health`、`GET /api/status` 与 `/docs`。
- Vue3 状态页面，显示真实 API 返回的服务连接、引擎运行时间与前端构建状态。
- 浏览器选择共享来源、本地视频预览和停止共享；支持拒绝授权、轨道结束、暂时无画面、尺寸变化及页面离开清理。
- 单视频会话的 WebRTC 协商、Python 接收/BGR 转换、最新帧缓存、接收 FPS/尺寸和后端 PNG 截图下载。
- 连接/首帧/无新帧/控制心跳超时清理，停止共享时关闭连接，失败后可在保留本地预览的情况下重新连接。
- 开发时 Vite 代理 API；构建后由 FastAPI 托管 `web/dist`。
- HTTP Host/Origin 限制和基础后端测试用例。
- 工作台提供 PNG/JPEG 预览和识别结果；独立设置页提供参考图、血蓝区域框选/坐标编辑、试识别和保存。截图与 WebRTC 帧调用同一 EngineService 识别函数。

API 的 capture/vision 能力表示已提供接收和基础血蓝识别函数，为 true；planning/input 为 false。角色识别、自动观察任务、连续识别和决策尚未接入。是否正在接收由 media 状态与累计帧数判断。共享画面与所选截图只发送给同机 Python，不使用外部中继，不连续录制；服务健康不等于识别准确率通过。

## 开发环境与验证状态

代码文件由虚拟机中的 Codex 编辑，依赖安装、构建、服务启动及 Windows 验证在宿主机执行。虚拟机与宿主机共享源码；虚拟机的工具版本和检查结果不能代表宿主机。不要在两侧同时安装或运行同一个 `.venv`/`node_modules`。

用户已确认宿主机首页、窗口共享和后端截图正确，浏览器到 Python 的基础接收已有实测依据；持续运行、断线清理、性能基线与具体测试结果仍待补齐。本次离线识别增量仅完成代码与静态检查，上传/框选/保存及真实比例误差待宿主机验证。以下命令以 Windows PowerShell 为例，在宿主机项目根目录执行。

建议 Python 3.12；当前包要求 Python ≥3.12。前端采用 Vite 7，需要 Node.js 20.19+（20.x）或 22.12+，与 [Vite 文档](https://vite.dev/guide/) 的运行要求相符；使用宿主机已有的 pnpm。具体 Python/pnpm 版本以你提供的宿主机结果为准。

## 1. 确认宿主机环境

```powershell
py -0p
node --version
pnpm --version
```

如果没有 `py` 启动器，改用 `python --version`，并确认对应解释器满足要求。命令不可用或版本不符时，将结果反馈后再调整安装步骤。

已收到宿主机反馈：Node.js 20.19.0、pnpm 10.34.1；用户已执行 Python 安装/检查步骤并成功启动项目，具体 Python 版本待回传。以下示例按 3.12 执行。每行是一条独立命令，执行成功后再运行下一行。

## 2. 安装 Python 依赖

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

命令直接使用虚拟环境解释器，不要求执行 PowerShell 激活脚本。已有适用虚拟环境时复用即可；也可以用明确的 Python 路径替代 `py -3.12`。

当前依赖为 FastAPI、Pydantic、Uvicorn、aiortc、NumPy、Pillow；PyAV 随 aiortc 安装，OpenCV 在识别阶段加入。已有虚拟环境时重新执行 pip install 更新依赖，无需重新创建 .venv。依赖清单目前为版本范围，宿主机验证后再固定实际版本。

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

打开 `http://127.0.0.1:5173`。页面使用相对 `/api` 路径，Vite 转发到本地后端；视频则通过 WebRTC 直接到达 Python。工作台状态在首次加载/刷新时请求，媒体连接建立后约每秒发送控制心跳并获取接收指标。

若修改后端端口，可复制 `web/.env.example` 为 `web/.env.local`，修改 `MAPLE_BACKEND_URL` 后重启 Vite。若修改前端端口，同步 `vite.config.ts` 和后端配置的 `dev_frontend_port`；固定端口被占用时先解决占用，不自动跳到另一端口。

安装后生成的 `web/pnpm-lock.yaml` 应保留并纳入版本管理。后续安装可在该锁文件验证后使用 `pnpm --dir web install --frozen-lockfile`。

### 验证窗口预览

更新 Python 依赖并重启后端，保持 Vite 运行，刷新页面，在 Chrome/Edge 中逐项检查：

1. 点击“选择窗口”，在浏览器选择器中选择目标应用窗口，确认画面实时变化、来源类型及尺寸显示正确。页面提供窗口偏好，最终仍以用户实际选择为准。
2. 点击“停止共享”，确认预览清空、尺寸消失、浏览器共享提示结束；再次选择可以重新共享。
3. 在浏览器自身的共享提示中停止共享，确认页面显示已停止并释放画面。
4. 取消选择或拒绝授权，确认出现可理解的提示，可再次选择，选择器等待期间不能重复发起请求。
5. 调整目标窗口尺寸，检查画面尺寸更新；最小化/遮挡时记录实际浏览器行为。轨道 mute 时显示画面暂不可用，不能保证所有冻结都会发出 mute 事件。
6. 刷新/关闭页面，确认共享结束；在选择器尚未确认时离开页面，也不应遗留捕获轨道。
7. 执行 `pnpm --dir web typecheck` 并反馈结果。预览不要求 build；生产构建仍由 `pnpm --dir web build` 检查。

仅通过 localhost、127.0.0.1 或 HTTPS 使用共享功能；不支持时页面显示原因。不要根据来源类型推断应用进程身份。

### 验证 Python 视频接收

先逐条执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app main.py tests
pnpm --dir web typecheck
```

重启后端（可用 VS Code F5），保持 `pnpm --dir web dev` 运行，选择窗口后自动连接 Python。确认“Python 正在接收”、累计帧数持续增长、后端尺寸匹配，点击“保存后端截图”，检查下载的 PNG 确实是共享窗口画面。当前没有增加前端依赖，无需为本次改动重新 pnpm install。

停止共享、浏览器停止、刷新/关闭页面后检查 `/api/status` 的 media 状态变为 closed/error，且 last_frame_id 为 null；再选择窗口应能建立新会话。断开后端应显示传输停止，本地预览可保留，重启后端后点击“重新连接 Python”。第二页面同时连接会得到已有会话提示，不能抢占原会话。

默认后端协商超时 15 秒、等待首帧 15 秒、无新帧 8 秒、控制心跳超时 10 秒；浏览器协商总上限 30 秒、ICE 收集 10 秒、心跳请求 3 秒。后端限制解码帧不超过 8,294,400 像素，截图编码最多一个在途请求。参数在 configs/default.json 中；浏览器参数目前写在 web/src/media.ts。关闭页面的 DELETE 请求只是尽力清理，后端超时机制覆盖未送达的情况。前台/后台计时器节流可能触发心跳超时，须按目标浏览器验证。

显示的“最新帧年龄”从后端收到已解码帧开始计算，“conversion_ms”只是 BGR 转换耗时，不是采集到解码或完整端到端延迟。缓存替换数表示未被消费者取走的旧帧被替换，不是网络丢包；目前没有识别消费者，计数持续增长属于预期。连续运行至少 10 分钟并记录 FPS、资源占用、尺寸变化和故障表现，P50/P95 全链路测量仍待补齐。

tests/test_media.py 包含本地合成视频协商、截图与超时检查；通过它仍不能替代真实浏览器/Windows 捕获验收。实现依据参考 [aiortc API](https://aiortc.readthedocs.io/en/latest/api.html) 和 [PyAV 视频接口](https://pyav.org/docs/stable/api/video.html)。

### 离线截图与血蓝调试

没有游戏应用时，先在左侧菜单“设置”配置区域，再回“工作台 → 离线截图”选择 `samples/normal.png` 并识别。页面地址分别为 `/#settings` 和 `/#workspace`，支持直接打开、刷新及浏览器前进/后退。采用 hash 导航，不需要新依赖或服务端路由回退；Vite 会更新前端。切换页面会清理当前图片或共享流，返回后需重新选择画面。

1. 上传 PNG/JPEG，服务端限制 10 MiB 和 8,294,400 像素，处理 EXIF 方向并提供与识别相同像素的 PNG 预览。全局只保留一张截图，下一张替换旧图；旧 ID 不再有效，不将上传图片写入 samples。
2. 默认配置 [configs/vision.json](configs/vision.json) 以 normal.png 的 1382 × 807 为参考。预置区域由截图外观估计，**是待校准的开发起点，不是已验收配置**。
3. 在“设置”上传参考图，选择血条、蓝条或经验条时，拖拽框选色条的完整内部长度，包括尚未填充的尾部，避开文字和边框；也可编辑 x/y/width/height。SVG 使用源图坐标。
4. 设置页中尺寸不同可“使用当前尺寸并清空区域”后重选；工作台遇到不匹配时只提示前往设置，不修改配置或缩放旧区域。
5. 设置页“试识别”可检查当前草稿；工作台“识别血蓝”使用已保存配置。结果显示比例、未知原因、连续性评分、帧编号和配置哈希；评分不是准确率。
6. 在设置页“保存区域配置”，服务端原子更新 configs/vision.json，并清除未保存提示。返回工作台后重新选择截图即可使用。未保存更改仅在设置页试用，离开后丢弃；手工修改 JSON 后需重启后端。
7. normal.png 中可见 HP 2534/3711（约 68.3%）、MP 48/513（约 9.4%），可用来人工核对；算法不读取这些数字，实际输出需由宿主机验证。只有一张截图不足以形成独立准确率报告。

经验条预填区域为 `(818, 780, 164, 12)`（x/y/width/height），按样本外观估计，可在设置页调整。当前仅显示并保存经验条区域，不计算经验比例；旧配置缺少 exp 时按未配置处理。

左下角角色信息栏预填 `player_info=(14, 763, 444, 34)`（紫框），角色名称单行预填 `player_name=(114, 778, 340, 17)`（绿框），坐标以 normal.png 的原图尺寸为准。在设置页选择对应目标，可框选、数字编辑、清空和保存；角色名称只框住姓名一行，避开职业和等级。旧配置缺少这两个字段时按未配置处理。切换参考尺寸会一并清空所有区域。当前仅保存/展示区域，尚未实现 OCR，也无需手填角色名；后续将从姓名区域自动读取角色身份。

没有有效填充颜色时 ratio 为 null，页面显示“未知”，不将空白当作零血/零蓝。当前不能可靠区分真实零值与配置错误；遮挡、颜色变化或错误 ROI 可能产生未知或不准确结果。必须用满条、半条、低值、零值/遮挡及不同录制会话扩充测试集，按方案冻结正式验收门槛，不能用单张调参图片宣布 P1 通过。

本增量的工程验证用例目标是：合法图片的预览/结果属于同一 ID，区域保存与重新读取一致，非法/越界输入被拒绝，已替换图片不可继续分析；合成色条误差不超过一列像素，无有效颜色或分辨率不符返回未知。这些用例不替代正式 P1 的真实数据、FPS 与 P95 门槛。

接口：POST /api/images（原始图片字节）、GET /api/images/{id}/preview、DELETE /api/images/{id}、GET/PUT /api/vision/profile、POST /api/images/{id}/analyze。POST /api/media/{id}/analyze 也接受相同 profile，使用已解码新鲜视频帧，分析后再次检查会话/尺寸/时效；当前共享页面还未加入自动识别循环。

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check app main.py tests
pnpm --dir web typecheck
```

请反馈上传、拖拽/坐标调整、保存重载及 normal.png 的实际比例结果。测试中新加入的合成图和 HTTP 用例见 [tests/test_vision.py](tests/test_vision.py)；在虚拟机未运行这些测试。

## 5. 构建并由后端托管

```powershell
pnpm --dir web build
```

构建包含 TypeScript 类型检查，产物写入 web/dist。重启后端，再打开 http://127.0.0.1:8765。工作台/设置使用单入口 hash 导航，刷新 /#settings 仍请求根页面，无需服务端路径回退。

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

预期健康状态为 ok，引擎为 idle（无自动任务），capture/vision 为 true，planning/input 为 false；无视频时 media 为 idle，连接后为 receiving，关闭后为 closed/error。构建并重启后 web_ui_ready 为 true。后端未启动时应显示连接失败。

请反馈环境版本、安装/检查命令结果、两个接口 JSON 和页面连接状态。失败时提供完整错误输出；无需提供凭据或整个依赖目录。只有宿主机验证通过后，才将对应运行验收条目标记完成。

## 目录

游戏截图保存在 `samples/`，用于没有游戏应用时的离线识别开发与调试；页面选择文件后上传到本地服务，不需要游戏窗口。

```text
app/
  cli.py              服务启动与配置入口
  config.py           配置校验和资源路径
  engine.py           核心服务生命周期及能力状态
  api/server.py       HTTP 接口与静态资源托管
  media/service.py    单会话协商、接收、心跳与超时清理
  media/frames.py     不可变帧元数据及最新帧缓存
  capture/images.py   截图解码与标准化预览
  vision/             血蓝识别、配置与结构化结果
  state/observation.py 同帧图像和结果快照
configs/default.json  默认本地配置
web/                  Vue3/Vite/TypeScript 状态页面
  src/components/ScreenCapture.vue  浏览器本地共享与生命周期管理
  src/media.ts        WebRTC 发送、心跳及截图下载
  src/components/ScreenshotLab.vue  离线预览、区域编辑与结果
  src/pages/SettingsPage.vue         独立区域设置页面
tests/test_server.py  API、生命周期、托管与访问限制检查
tests/test_media.py   合成视频协商、截图、缓存与故障检查
tests/test_vision.py  合成色条、上传、分析及配置保存检查
main.py               源码启动入口
```

开发与交付须遵循 [AGENTS.md](AGENTS.md)，同步待办与技术方案。
