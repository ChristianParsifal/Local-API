# Antares Gateway 验证记录

验证日期：2026-11-17，Windows 11 / Python 3.12.14 / PyInstaller 6.22.3。

- 后端4项回归测试通过：本地密钥与停用、数据库持久化/中断恢复/导出备份、缓存与推理Token计费、HTTP普通请求与分块SSE转发、Anthropic缓存用量合并、OpenRouter价格同步/汇率/版本/别名/阶梯/1小时缓存/负价格排除。
- 真实访问 https://openrouter.ai/api/v1/models 成功，独立测试数据库导入462个模型；测试时汇率6.679257 CNY/USD。软件使用同步时汇率，此数字不写死为官方汇率。
- 前端Node语法和DOM引用检查通过；真实WebView2六页面切换与Python桥接通过。
- 最终单文件EXE启动测试通过：本机网关正常监听，未提供本地密钥返回HTTP401，创建SQLite数据库。
- 最终EXE桌面模式测试通过：Windows实际创建Antares API Monitor窗口，后台网关可访问。
- 原版EXE保留；新版位于dist/Antares Gateway.exe，大小29,576,184字节。
- 测试使用独立目录，未使用用户上游密钥；测试进程已清理。依赖一致性检查pip check通过。

尚未使用真实Agent及用户上游密钥做模型调用验收；普通和流式转发使用本机模拟上游测试。未自动修改用户开机启动项进行验收。托盘生命周期已实现，桌面窗口创建已验证，实际点击托盘及登录后自启仍建议用户日常使用时验收。

当前范围是HTTP JSON/SSE及Token估算；Responses WebSocket和图片、音频专用端点未接入，非Token附加费用不包含在估算内。长期大量记录的全量聚合性能尚未压测。
