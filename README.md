# Evil Twin 管理系统

基于 Flask、hostapd、dnsmasq 的 Evil Twin 实验管理后台，支持 WiFi 扫描、无线网卡选择、热点配置、密码记录和 MAC 记录。

仅供安全研究和授权测试使用。不要在未授权网络上运行。

## 功能

| 模块 | 说明 |
| --- | --- |
| WiFi 扫描 | 扫描周围无线网络，显示 SSID、BSSID、信号、信道、加密方式 |
| 无线网卡选择 | 自动发现无线接口，支持在后台选择扫描/热点网卡并保存到数据库 |
| SSH 风险提示 | 标注已连接 SSID、有 IP、默认路由的网卡，避免误选正在负责 SSH 的网卡 |
| USB 诊断 | 显示 `lsusb` 是否识别 Netgear/MediaTek USB WiFi，以及 `iw dev` 是否创建无线接口 |
| 热点配置 | 配置伪造 SSID、信道、网卡和热点密码 |
| 记录页面 | 保存最近密码记录和 MAC/IP/User-Agent 信息 |

## 推荐网络架构

示例：

| 接口 | 用途 |
| --- | --- |
| `wlo2` | 连接家庭 WiFi、SSH、服务器上网 |
| `wlx289401bcd8a4` | USB WiFi，用于扫描和实验 |

后台会优先推荐非默认路由、未连接 SSID 的 USB 无线网卡。若选择默认路由网卡，页面会提示：

```text
这个网卡正在用于服务器联网/SSH，使用它可能导致远程连接断开。
```

## 系统依赖

Ubuntu/Debian：

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq aircrack-ng python3 python3-venv python3-full iw wireless-tools usbutils
```

`iwlist` 来自 `wireless-tools`，用于在 `iw dev <iface> scan` 失败或无结果时 fallback。

## Python 依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 初始化数据库

```bash
python3 init_db.py
```

新数据库不会把 `config.network_interface` 默认写死成 `wlan0`。程序启动或访问 `/api/interfaces` 时会自动检测当前可用无线网卡；如果数据库里保存的接口不存在，会自动选择推荐接口并写回数据库。

## 启动

项目中的扫描、启动热点等操作会调用 `sudo ip`、`sudo iw`、`sudo iwlist`、`sudo hostapd`、`sudo dnsmasq`。如果没有配置免密 sudo，可以直接用 sudo 启动：

```bash
sudo venv/bin/python app.py
```

浏览器打开：

```text
http://<服务器IP>:5000
```

如果曾经用 sudo 启动过程序，`evil_twin.db` 或 `evil_twin.log` 可能变成 root 所有。普通用户再次启动前先修复权限：

```bash
sudo chown -R jun:jun /home/jun/EvilTwin
```

程序启动时会检查 `evil_twin.db` 和 `evil_twin.log` 是否可写；如果不可写，会提示：

```bash
请执行 sudo chown -R $USER:$USER /home/jun/EvilTwin
```

## 一键部署

```bash
git clone https://github.com/treysiz/EvilTwin.git
cd EvilTwin
chmod +x deploy.sh
sudo ./deploy.sh
sudo venv/bin/python app.py
```

`deploy.sh` 会安装系统依赖、创建虚拟环境、安装 Python 依赖并初始化数据库。

## WiFi 扫描逻辑

扫描前会先启用当前选择的接口：

```bash
sudo ip link set <iface> up
```

然后优先尝试：

```bash
sudo iw dev <iface> scan
```

如果失败或结果为空，自动 fallback：

```bash
sudo iwlist <iface> scanning
```

`/api/scan` 返回格式保持前端兼容：

```json
{
  "status": "success",
  "results": [
    {
      "ssid": "xinhome",
      "bssid": "AA:BB:CC:DD:EE:FF",
      "channel": 6,
      "signal": -39,
      "security": "WPA2",
      "frequency": 2437
    }
  ],
  "count": 1
}
```

失败时会返回 `stderr`、`stdout` 或诊断信息，方便排查权限、驱动和接口状态问题。

## USB 网卡诊断

`/api/interfaces` 会返回：

- 当前检测到的无线接口列表
- 当前数据库保存的 `network_interface`
- 推荐接口
- 每个接口的连接 SSID、IPv4、默认路由状态
- `lsusb` 是否看到 Netgear/MediaTek/MT7925/无线设备
- `iw dev` 是否创建无线接口

如果 `lsusb` 已识别 USB WiFi，但没有对应 USB 无线接口，会提示：

```text
USB WiFi 已识别但驱动未创建接口，可能需要重新插拔 USB 网卡或冷重启。
```

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 管理后台首页 |
| `GET` | `/api/config` | 获取配置 |
| `POST` | `/api/config` | 更新配置 |
| `GET` | `/api/interfaces` | 获取无线网卡列表和诊断信息 |
| `POST` | `/api/scan` | 扫描周围 WiFi |
| `POST` | `/api/start` | 启动热点 |
| `POST` | `/api/stop` | 停止热点 |
| `GET` | `/api/status` | 获取 hostapd/dnsmasq 状态 |
| `GET` | `/api/passwords` | 获取密码记录 |
| `DELETE` | `/api/passwords` | 清空密码记录 |
| `GET` | `/api/macs` | 获取 MAC 记录 |
| `DELETE` | `/api/macs` | 清空 MAC 记录 |

## CI

GitHub Actions 会在 push 和 pull request 时运行：

```bash
python -m py_compile app.py init_db.py
python -m unittest discover -s tests
```

单元测试覆盖 `iwlist` 扫描输出解析，避免 fallback 解析逻辑回归。

## 常见问题

**扫描显示没有网络**

先在服务器上确认接口是否存在：

```bash
iw dev
ip link show <iface>
```

如果 `iw dev <iface> scan` 报 `Network is down (-100)`，程序会自动尝试 `ip link set <iface> up` 并 fallback 到 `iwlist <iface> scanning`。

**USB 网卡 lsusb 看得到，但 iw dev 看不到**

可能是驱动初始化失败，例如 MT7925U 偶发 `probe ... failed with error -110`。重新插拔 USB 网卡或冷关机后再试。

**普通用户启动报 PermissionError**

执行：

```bash
sudo chown -R $USER:$USER /home/jun/EvilTwin
```
