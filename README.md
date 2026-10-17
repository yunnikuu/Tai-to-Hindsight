# Tai → Hindsight 数据迁移工具

Windows 中文桌面工具，把 Tai 的应用使用汇总迁移到 Hindsight 本机数据库。当前源码版本为 **v1.1.0**，使用 Python 3.12、CustomTkinter 和 SQLite。

## 使用
**使用前请务必备份您的Hindsight数据库文件 以防丢失数据**
1. 先运行一次 Hindsight，确保已有初始化的数据库。
2. 打开工具，用“智能定位”或“扫描…”找到 Tai 来源和 Hindsight 目标。也可选择数据库、程序或快捷方式。
[Tai数据位置通常在安装目录下 Tai\Data\data.db    Hindsight通常在\AppData\Roaming\Hindsight\hindsight.sqlite（在Hindsight内可以打开数据目录） ]
4. 定位时可保持软件运行；**预览和迁移前完全退出 Tai、Hindsight 及托盘进程**。

备份与报告保存在目标数据库旁的 `tai-migration-backups` 文件夹。恢复时需要备份的同名 `.json` 校验文件；恢复会撤回备份之后整个数据库的全部变化，恢复前会额外创建安全备份。

Tai 只有小时/日汇总，导入的活动时间段是重建值，无法还原精确会话、真实窗口标题、截图或网页记录

## 运行源码

在仓库根目录执行：

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 launcher.py
```


## 已知问题

使用 Win+D 显示桌面后应用窗口可能无法恢复


本工具独立开发，与 Tai、Hindsight 官方无隶属关系。
