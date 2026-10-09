# 本地前后端守护

Windows / PowerShell 7 下，在仓库根目录执行：

```powershell
& './scripts/dev-services.ps1' start
& './scripts/dev-services.ps1' status
& './scripts/dev-services.ps1' stop
```

Python 需要已有后端依赖及 `psutil`；Node 使用已安装的前端依赖。可用 `-Python 'D:/anaconda/python.exe' -Node 'D:/node.js/node.exe'` 指定解释器。

`start` 隐藏启动单实例守护，管理 127.0.0.1:5173 的 Vite 和 127.0.0.1:8000 的 Daphne。对同一可执行文件、工作目录和参数的已有服务直接接管；遇到其他端口占用者只记录，不停止它。

每 5 秒检查进程，退出后以 5 秒起、最多 300 秒的退避重新启动。稳定运行 5 分钟后清除失败次数。物理可用内存低于 256 MB 或 Windows 提交内存达到 95% 时暂停新启动，恢复后继续；内存紧张不会触发杀进程。每分钟记录内存与服务状态，后续退出时记录退出码（已接管的旧进程退出码可能未知）。

日志与 PID 在 `.codex-runtime/dev-services/`，`status.json` 包含最近快照，使用 `status` 判断守护是否仍存活。`guard.log` 按 3 MB 轮转，保留 3 个旧文件；守护启动的服务日志为 `frontend.out/err.log`、`backend.out/err.log`，只在下次启动前轮转并保留 3 代，单次长运行日志大小没有硬限制。接管的服务仍写其原有日志。

`stop` 只关闭守护，保留前后端。计划停止或重启某个服务时，先 `stop`，核对该服务 PID、命令行和工作目录再停止；随后 `start` 可启动缺失服务并重新接管其余服务。

这是本机开发进程退出恢复，不是开机自启，也不检测应用卡死、网络断开或浏览器/WebGL 故障。机器重启、守护本身被退出后需要重新执行 `start`；不能保证在系统内存耗尽时持续可用。

验证使用一次性进程，不停止业务服务：

```powershell
python scripts/test_dev_services.py
```
