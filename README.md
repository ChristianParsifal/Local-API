# Antares Gateway

**面向 Windows 的本机 API 网关与用量监控桌面应用。**

Antares Gateway 将多个 Agent、Harness 和其他兼容客户端的请求汇集到本机，按应用和模型记录 Token 用量，并使用 OpenRouter 模型价格估算人民币费用。

```text
Agent / Harness ── 本地地址 + 应用密钥 ──> Antares Gateway ──> 上游 API
                                               │
                                               ├── 用量与费用统计
                                               └── SQLite 本地数据库
```

## 功能

- **统一接入**：为每个客户端生成独立的本地密钥，区分请求来源。
- **请求监控**：查看请求状态、模型、耗时、Token 用量及估算费用，并按来源、模型、时间和状态筛选。
- **人民币费用估算**：从 OpenRouter 同步美元单价，按美元兑人民币汇率换算，支持模型别名和价格版本记录。
- **流式响应**：转发普通 HTTP 响应及 SSE 流式响应，并尝试读取上游返回的用量信息。
- **桌面常驻**：支持系统托盘、关闭窗口后继续运行和开机启动选项。
- **本地数据管理**：使用 SQLite 保存配置与请求记录，支持 CSV 导出和数据库备份。
- **预算提醒**：设置月预算，达到阈值后在界面显示提醒。

## 运行环境

- Windows，桌面界面需要 Microsoft Edge WebView2 Runtime。
- 需要一个兼容受支持接口的上游 API 地址和密钥。
- 同步模型价格需要连接 [OpenRouter 模型接口](https://openrouter.ai/api/v1/models)；自动获取汇率使用 [ExchangeRate API](https://open.er-api.com/v6/latest/USD)。

## 快速开始

### 1. 启动应用

运行打包后的 `Antares Gateway.exe`。从项目源码自行构建时，输出文件位于 `dist/Antares Gateway.exe`；构建方法见下文。

默认网关地址为：

```text
http://127.0.0.1:18765/v1
```

### 2. 配置上游连接

打开 **上游连接**，填写名称、协议、上游 API Base URL 和真实 API Key，保存后可使用连接测试。

每种协议同时启用一个上游：启用新的同协议连接时，旧连接会被停用。上游密钥由 Windows DPAPI 加密保存在本机。

### 3. 同步价格

打开 **模型与价格**，点击同步 OpenRouter 价格。应用将美元单价按汇率转换为人民币每百万 Token 价格。同步时可选择自动更新汇率，或沿用设置中填写的汇率。

如果客户端使用的模型名与 OpenRouter 模型 ID 不同，在此页面配置模型别名映射。未匹配到价格的请求会显示为待计价。

### 4. 接入客户端

打开 **接入应用**，为每个 Agent 或 Harness 创建一个应用。复制生成的本地密钥；完整密钥仅在创建时显示一次。

在客户端的 API 设置中填写：

| 配置项 | 值 |
| --- | --- |
| Base URL | `http://127.0.0.1:18765/v1`，或应用中显示的实际地址 |
| API Key | 刚生成的本地应用密钥 |
| 模型 | 上游服务支持的模型名 |

客户端发起请求后，可在 **总览** 和 **请求记录** 中查看数据。实际 Base URL 的填写格式取决于客户端；请确认最终请求路径与下表中的端点一致。

> 只有经过本机网关的请求会被记录。关闭窗口并保留托盘时，网关继续运行；从托盘退出应用后，客户端将失去到本地网关的连接。

## 接口支持

| 本地端点 | 上游协议 |
| --- | --- |
| `/v1/chat/completions` | OpenAI 兼容 |
| `/v1/completions` | OpenAI 兼容 |
| `/v1/responses` | OpenAI 兼容 |
| `/v1/models` | OpenAI 兼容 |
| `/v1/messages` | Anthropic Messages |

当前实现处理 HTTP JSON 和 SSE。Responses WebSocket、后台任务轮询及图片、音频专用端点尚未接入。对于流式 Chat Completions，网关默认请求上游返回流式用量；具体兼容性取决于上游实现。

## 费用与数据口径

- 单价来源为 OpenRouter，使用同步时保存的汇率换算为人民币；**估算金额与实际上游账单可能不同**。
- 输入、输出、缓存读取和支持的缓存写入及阶梯价格按已保存的价格规则计算；推理 Token 不额外重复计入输出。
- 请求未返回完整用量时显示未知；缺少模型价格或所需计价字段时显示待计价。
- 图片、音频、搜索等非 Token 附加费用未包含在 Token 估算中。
- 历史请求保留当时的价格版本与计算结果；更新价格或汇率影响之后的请求。
- 默认保存用量和请求元数据，不保存提示词及模型回答正文。

默认数据目录为 `%LOCALAPPDATA%\AntaresGateway`，数据库文件为 `monitor.sqlite3`。数据库备份包含配置和用量记录；其中受 DPAPI 保护的上游密钥通常需要原 Windows 用户账户才能解密。

## 从源码运行

使用 Python 3.12 创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

可选启动参数：

```powershell
python app.py --minimized             # 启动后隐藏窗口
python app.py --headless              # 仅启动网关
python app.py --port 18765            # 设置监听端口并保存
python app.py --data-dir .\local-data # 使用指定数据目录
```

`--port` 会保存到所用数据目录的设置中。同一数据目录只允许一个实例运行。

## 测试

```powershell
python -m unittest discover -s tests -p test_backend.py -v
```

后端测试使用本机模拟上游，覆盖请求转发、流式用量、密钥、持久化和价格计算。桌面与打包程序验证还可运行：

```powershell
python smoke_desktop.py
python smoke_exe.py
```

这些脚本使用独立测试数据目录；`smoke_exe.py` 需要先完成下方打包。测试覆盖情况见 [VALIDATION.md](VALIDATION.md)。实际 Agent 与上游服务的兼容性仍需使用自己的配置验证。

## 打包

安装依赖后，在项目根目录运行：

```powershell
python -m PyInstaller --noconfirm "Antares Gateway.spec"
```

生成的单文件程序位于 `dist/Antares Gateway.exe`。

## 常见问题

**请求没有显示在看板中？** 先确认应用仍在运行、客户端的 Base URL 指向本机网关，并使用了该客户端对应的本地密钥。随后检查请求记录和上游连接状态。

**为什么费用显示待计价？** 检查是否已同步价格、上游是否返回完整用量，以及请求模型名是否与 OpenRouter 模型 ID 一致；必要时设置别名。

**为什么估算费用与账单不同？** OpenRouter 报价与实际上游价格、汇率、折扣及计费方式可能不同，部分非 Token 费用也未计入。请以实际上游账单为准。

**应用启动失败？** 检查端口是否已被占用，以及 Microsoft Edge WebView2 Runtime 是否可用。启动异常记录位于 `%LOCALAPPDATA%\AntaresGateway\startup-error.log`。

## 技术栈

Python、FastAPI、Uvicorn、HTTPX、SQLite、pywebview、pystray 和 PyInstaller。
