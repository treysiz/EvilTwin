#!/bin/bash
set -e

echo "===================================="
echo "  Evil Twin Attack System 部署脚本"
echo "===================================="
echo ""

# 检测系统
if [ "$(id -u)" -ne 0 ]; then
    echo "[!] 请用 root 权限运行: sudo ./deploy.sh"
    exit 1
fi

# 1. 安装系统依赖
echo "[1/4] 安装系统依赖..."
if command -v apt &>/dev/null; then
    apt update -qq
    apt install -y -qq hostapd dnsmasq aircrack-ng python3 python3-venv python3-full iw wireless-tools usbutils
elif command -v dnf &>/dev/null; then
    dnf install -y hostapd dnsmasq aircrack-ng python3 python3-venv iw wireless-tools usbutils
elif command -v pacman &>/dev/null; then
    pacman -S --noconfirm hostapd dnsmasq aircrack-ng python python-virtualenv iw wireless_tools usbutils
else
    echo "[!] 不支持的包管理器，请手动安装: hostapd dnsmasq aircrack-ng python3 python3-venv iw wireless-tools usbutils"
    exit 1
fi

# 2. 创建 Python 虚拟环境
echo "[2/4] 配置 Python 虚拟环境..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
elif [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
fi

venv/bin/pip install --quiet -r requirements.txt 2>/dev/null || pip install --quiet -r requirements.txt

# 3. 初始化数据库
echo "[3/4] 初始化数据库..."
venv/bin/python init_db.py

# 4. 完成
echo "[4/4] 部署完成!"
echo ""
echo "===================================="
echo "  启动 Evil Twin 攻击系统:"
echo "    cd $(pwd)"
echo "    sudo venv/bin/python app.py"
echo ""
echo "  浏览器打开: http://localhost:5000"
echo "===================================="
