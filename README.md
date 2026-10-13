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
- 独立识别测试页提供 PNG/JPEG 预览、血蓝数值/比例、姓名裁剪、本地 OCR 文字与置信度；设置页提供参考图、区域框选/坐标编辑、试识别和保存。截图与 WebRTC 帧调用同一 EngineService 识别函数。

API 的 capture/vision 能力表示已提供接收、基础血蓝和姓名 OCR 识别函数，为 true；planning/input 为 false。场景人物定位、自动观察任务、连续识别和决策尚未接入。是否正在接收由 media 状态与累计帧数判断。共享画面与所选截图只发送给同机 Python，不使用外部中继，不连续录制；服务健康不等于识别准确率通过。

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

当前依赖为 FastAPI、Pydantic、Uvicorn、aiortc、NumPy、Pillow 和 rapidocr-onnxruntime==1.4.4；PyAV 随 aiortc 安装，ONNX Runtime/OpenCV 随 OCR 包安装。已有虚拟环境时重新执行 pip install 更新依赖，无需重新创建 .venv。OCR 适配按 1.4.4 接口固定包版本，其余仍为版本范围；固定版本不代表宿主机兼容验证已通过。

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

### 识别测试：离线截图、血蓝与姓名 OCR

没有游戏应用时，先在左侧菜单“设置”配置区域，再进入“识别测试”选择 `samples/normal.png` 并识别。识别测试地址为 `/#recognition`，设置为 `/#settings`，工作台为 `/#workspace`，支持直接打开、刷新及浏览器前进/后退。采用 hash 导航，不需要新增前端依赖或服务端路由回退；Vite 会更新前端。切换页面会清理当前图片或共享流，返回后需重新选择画面。

1. 上传 PNG/JPEG，服务端限制 10 MiB 和 8,294,400 像素，处理 EXIF 方向并提供与识别相同像素的 PNG 预览。全局只保留一张截图，下一张替换旧图；旧 ID 不再有效，不将上传图片写入 samples。
2. 默认配置 [configs/vision.json](configs/vision.json) 以 normal.png 的 1382 × 807 为参考。预置区域由截图外观估计，**是待校准的开发起点，不是已验收配置**。
3. 在“设置”上传参考图，选择血量数字、蓝量数字、经验数字或角色文字，只框住对应文字一行；也可编辑 x/y/width/height。SVG 使用源图坐标。
4. 设置页中尺寸不同可“使用当前尺寸并清空区域”后重选；识别测试遇到不匹配时只提示前往设置，不修改配置或缩放旧区域。
5. 设置页“试识别”可检查当前草稿；识别测试页“开始识别”使用已保存配置。结果显示比例、未知原因、帧编号和配置哈希；模型置信度不是准确率。
6. 在设置页“保存区域配置”，服务端原子更新 configs/vision.json，并清除未保存提示。返回识别测试后重新选择截图即可使用。未保存更改仅在设置页试用，离开后丢弃；手工修改 JSON 后需重启后端。
7. normal.png 中可见 HP 2534/3711（约 68.3%）、MP 48/513（约 9.4%），可用来人工核对；数字由新增 OCR 读取，实际输出需由宿主机验证。只有一张截图不足以形成独立准确率报告。

血蓝与经验只识别文字，不保留色条区域或颜色计算。配置只接受当前文字区域和 OCR 阈值字段；hp/mp/exp 及颜色阈值等废弃字段直接拒绝，不兼容、不忽略、不自动迁移。API 不再返回 hp/mp 色条结果，血蓝仅返回 hp_numbers/mp_numbers，原文字与置信度保留在详情。

左下角角色信息栏预填 `player_info=(14, 763, 444, 34)`（紫框），角色名称单行预填 `player_name=(114, 778, 340, 17)`（绿框），坐标以 normal.png 的原图尺寸为准。在设置页选择对应目标，可框选、数字编辑、清空和保存；角色名称只框住姓名一行，避开职业和等级。旧配置缺少这两个字段时按未配置处理。切换参考尺寸会一并清空所有区域。当前通过本地 OCR 从姓名单行区域读取名字，无需手填；角色信息栏整体只保存/展示区域。

按 normal.png 新增三项位置预设（x/y/width/height）：角色等级 `player_level=(62, 772, 28, 19)`、角色职业 `player_job=(114, 763, 140, 15)`、经验数字 `exp_text=(843, 762, 140, 14)`。设置页可选择对应目标查看、调整、清空并保存；等级框避开 LV.，职业框只包含上一行职业，经验数字框包含经验值及括号内百分比，避开 EXP 标签。等级、职业和经验数字已接入本地 OCR；旧配置缺少字段时对应结果为未知。重启后端、刷新 Vite 后上传 normal.png 核对框位置，无需新增依赖或 build。

新增 OCR 依赖后，在宿主机项目根目录执行 `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`，再重启后端；前端没有新增依赖，Vite 刷新即可。OCR 使用 [RapidOCR 1.4.4](https://github.com/RapidAI/RapidOCR/tree/v1.4.4/python/rapidocr_onnxruntime) 随包模型在本地 CPU 执行，首次有效姓名识别会初始化模型，可能较慢。

在“识别测试”上传 normal.png，点击“开始识别”。桌面左侧截图、右侧信息区集中显示角色名称、血量当前值/总值及比例、蓝量当前值/总值及比例、等级、职业和经验值及画面百分比；窄屏优先显示结果。裁剪图、置信度和帧/配置记录放在默认折叠的“识别详情”，需要核对姓名时再展开。结果包括姓名、原始待核对文字（仅低置信度）、模型置信度、姓名处理耗时、总耗时与配置/帧信息。姓名/职业及血蓝/经验最低置信度默认 0.8，等级独立默认 0.6，可在设置页调整并保存，不代表准确率或正式验收阈值；文字为空、多文字块或低置信度显示未知，错误区域也可能产生误读。识别请求最长等待 60 秒，超时后台工作未必已结束，在其结束前再次调用返回忙碌；初始化缺依赖/失败须修复后重启后端，各字段独立返回结果或未知。地图识别和场景人物定位尚未实现。

血蓝数字区域默认 `hp_text=(495, 762, 142, 14)`、`mp_text=(664, 762, 141, 14)`，只覆盖色条上方当前值/总值文字。可在设置页选择“血量数字”或“蓝量数字”调整并保存；旧配置未含字段时需配置，不自动猜测位置。数字最低置信度默认 0.8，可独立调整。读取合法数值后显示“当前 / 总值”，数值比例由两数相除；比例只按读取的当前值/总值计算，不做颜色估计。空白、低置信度、格式错误、总值为零或当前超过总值时显示未知，不反推缺失数字。`0/100` 可读作有效零值。默认预填区域及真实数字识别需宿主机核对，裁剪和 OCR 原文/置信度位于折叠详情。

等级、职业和经验同帧读取，样本人工参照为等级 55、职业“剑客”、经验 `503851[54.37%]`，不把这些参照写成实际结果。等级只接受正整数（上限 9999），职业检查基本文字格式，经验必须同时包含整数和括号内百分比（0–100）；错误/空白/低置信度时对应结果为未知。模型置信度和真实准确率不同，职业未做职业列表校验。经验总值不反推，不分析色条颜色。折叠详情可核对三项原文、裁剪图、置信度与耗时，等级使用独立 `player_level_min_confidence=0.6`，数字阈值用于血蓝/经验，文字阈值用于姓名/职业。旧配置缺少等级阈值时默认 0.6；设置页可编辑并保存，手动修改 JSON 后需重启后端。此次按用户反馈的等级 OCR 置信度约 0.679 调整，重新验证待完成，不代表原 0.8 阈值验收通过。

本次复用已有本地 OCR 依赖，无需新增安装包；重启后端、刷新 Vite。若仍提示 OCR 依赖缺失，按前述 pip 安装步骤处理后重启。宿主机项目根目录执行 `.\.venv\Scripts\python.exe -m pytest tests/test_character.py tests/test_numbers.py tests/test_names.py tests/test_vision.py`、`.\.venv\Scripts\python.exe -m ruff check app main.py tests` 和 `pnpm --dir web typecheck`，预期检查通过。之后在页面核对 normal.png 的 2534/3711 和 48/513，以及零值、满值和遮挡样本。桩和解析测试通过不代表真实 OCR 准确率已通过。

宿主机在项目根目录执行 `.\.venv\Scripts\python.exe -m pytest tests/test_names.py tests/test_vision.py` 的返回值桩测试只验证结果策略、API 同帧关联和并发，不验证真实模型。真实验收需在页面用多张姓名、空白/遮挡、错误区域及职业与姓名同时入框样本人工核对；normal.png 仅为开发样本，不能宣布独立准确率通过。

无法读取合法且足够可信的血蓝数字时 current/total/ratio 为 null，页面显示未知；能明确读出 0/正总值时输出零。OCR 空白、遮挡或错误区域不可通过颜色结果补齐，必须扩充独立样本评估数字准确率。

本增量的工程验证用例目标是：合法图片的预览/结果属于同一 ID，区域保存与重新读取一致，非法/越界输入被拒绝，已替换图片不可继续分析；数字格式/范围/阈值不符或分辨率不符返回未知，含废弃/未知字段的配置被拒绝。这些用例不替代正式 P1 的真实数据、FPS 与 P95 门槛。

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

构建包含 TypeScript 类型检查，产物写入 web/dist。重启后端，再打开 http://127.0.0.1:8765。工作台/识别测试/设置使用单入口 hash 导航，刷新 /#settings 仍请求根页面，无需服务端路径回退。

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
  vision/             血蓝、姓名 OCR、配置与结构化结果
  state/observation.py 同帧图像和结果快照
configs/default.json  默认本地配置
web/                  Vue3/Vite/TypeScript 状态页面
  src/components/ScreenCapture.vue  浏览器本地共享与生命周期管理
  src/media.ts        WebRTC 发送、心跳及截图下载
  src/components/ScreenshotLab.vue  离线预览、区域编辑与结果
  src/pages/RecognitionTestPage.vue  独立识别测试页面
  src/pages/SettingsPage.vue         独立区域设置页面
tests/test_server.py  API、生命周期、托管与访问限制检查
tests/test_media.py   合成视频协商、截图、缓存与故障检查
tests/test_vision.py  上传、OCR 同帧结果、配置保存与未知字段拒绝检查
main.py               源码启动入口
```

开发与交付须遵循 [AGENTS.md](AGENTS.md)，同步待办与技术方案。
