# Evil Twin攻击管理系统 (ETA)

> 基于 Flask + hostapd + dnsmasq 的 Evil Twin 攻击系统，支持 Web 管理后台、WiFi 密码钓鱼捕获、MAC 地址记录、多语言自适应钓鱼页面。

## 功能

| 模块 | 说明 |
|------|------|
| 🔍 周围 WiFi 扫描 | 自动扫描附近无线网络，显示 SSID/信号/信道/加密，一键克隆目标 |
| ⚙️ 热点配置 | 自定义伪造 SSID、信道、网卡接口名，自动检测无线网卡 |
| 🎣 钓鱼认证页 | 15 种语言自适应，根据设备语言自动切换，阿拉伯语 RTL 支持 |
| 📋 密码记录 | FIFO 10 条上限，触发器自动清理旧记录 |
| 📡 MAC 地址记录 | 记录客户端 IP、User-Agent，含时间戳 |
| ▶️ 攻击控制 | 一键启动/停止 hostapd + dnsmasq，DNS 劫持重定向到钓鱼页 |

## 系统架构

```
Web 管理后台 (Flask)
  ├── SSID/信道配置
  ├── WiFi 扫描 (iw / netsh fallback)
  ├── 密码记录 (SQLite, FIFO 10)
  └── MAC 记录
        │
        ▼
核心攻击引擎
  ├── hostapd   → 伪造热点
  ├── dnsmasq   → DNS 劫持
  └── Flask     → 钓鱼页服务
        │
        ▼
    无线网卡 (AP 模式)
```

## 硬件要求

- 支持 AP 模式的 USB 无线网卡
- 推荐芯片：MT7925 / MT7612U / RTL8812AU / AR9271
- 操作系统：Linux（Ubuntu 20.04+ / Kali / Debian / Arch）

> ⚠️ Windows WSL2 仅支持 Web 后台和扫描功能，创建热点需实体 Linux 或 USB 网卡直通。

## 一键部署

```bash
git clone https://github.com/treysiz/EvilTwin.git
cd EvilTwin
chmod +x deploy.sh
sudo ./deploy.sh
sudo venv/bin/python app.py
```

`deploy.sh` 自动完成：系统依赖安装 → Python 虚拟环境 → Flask → 数据库初始化。

浏览器打开 `http://<服务器IP>:5000`

## 手动部署

### 1. 安装系统依赖

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq aircrack-ng python3 python3-venv python3-full iw
```

### 2. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask
```

### 3. 初始化数据库

```bash
python3 init_db.py
```

### 4. 启动服务

```bash
sudo venv/bin/python app.py
```

> 必须用 `sudo` — hostapd / dnsmasq / ip 命令需要 root 权限。

## 使用流程

```
1. 插上网卡 → 页面自动检测接口名
2. 点"扫描" → 查看周围 WiFi
3. 选目标 → 点"克隆" → SSID 和信道自动填入
4. 保存配置 → 点"启动攻击"
5. 客户端连接后访问任意网站 → 被重定向到钓鱼页
6. 输入密码 → 自动记录到数据库
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 管理后台首页 |
| GET | `/passwords` | 密码记录页面 |
| GET | `/macs` | MAC 记录页面 |
| GET | `/portal` | 钓鱼认证页 |
| POST | `/capture` | 接收密码（钓鱼页提交）|
| GET | `/api/config` | 获取配置 |
| POST | `/api/config` | 更新配置 |
| GET | `/api/passwords` | 获取密码列表 |
| DELETE | `/api/passwords` | 清空密码 |
| GET | `/api/macs` | 获取 MAC 列表 |
| DELETE | `/api/macs` | 清空 MAC |
| GET | `/api/status` | 运行状态 |
| GET | `/api/interfaces` | 自动检测无线网卡 |
| POST | `/api/scan` | 扫描周围 WiFi |
| POST | `/api/start` | 启动攻击 |
| POST | `/api/stop` | 停止攻击 |

## 数据库

SQLite 单文件 `evil_twin.db`，含三张表：

- **config** — SSID / 信道 / 网卡接口名
- **password_logs** — 密码 + 来源 IP + 时间（FIFO 10 条上限）
- **mac_logs** — MAC 地址 + IP + User-Agent + 时间

## 安全问题

⚠️ **仅供安全研究和授权测试使用。** 未经授权对他人网络进行 Evil Twin 攻击属违法行为。使用者需自行承担法律责任。

## 常见问题

**Q: 启动攻击失败？**
A: 检查 `iw dev` 是否能看到网卡，确认支持 AP 模式：`iw list | grep "Supported interface modes" -A 10 | grep "* AP"`

**Q: 扫描无结果？**
A: Linux 用 `iw scan`，Windows WSL 自动 fallback 到 `netsh`。确保网卡已插入且驱动正常。

**Q: 客户端连上但没跳转到钓鱼页？**
A: 确认 dnsmasq 运行中（`GET /api/status`），DNS 劫持配置正确。

**Q: Flask 端口被占用？**
A: 修改 `app.py` 末尾的 `port=5000` 为其他端口。
