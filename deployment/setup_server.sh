#!/bin/bash

# Script setup server Oracle Cloud cho dự án Radar BDS
# Hệ điều hành khuyến nghị: Ubuntu 22.04

echo "--- 🚀 Bắt đầu thiết lập Server Radar BDS ---"

# 1. Cập nhật hệ thống
sudo apt update && sudo apt upgrade -y

# 2. Cài đặt Python và các thư viện cần thiết
sudo apt install -y python3-pip python3-venv nginx git curl sqlite3

# 3. Cài đặt các thư viện cho Playwright (Crawler)
sudo npx -y playwright install-deps

# 4. Tạo thư mục dự án và môi trường ảo
mkdir -p ~/radar_bds
cd ~/radar_bds
python3 -m venv venv
source venv/bin/activate

# 5. Cài đặt requirements (Giả định anh đã có file requirements.txt)
# Ở đây em list các package chính
pip install flask gunicorn pandas requests beautifulsoup4 playwright
playwright install chromium

echo "--- 🛠 Cấu hình Gunicorn Service ---"
# Tạo file service để web luôn chạy ngầm
sudo bash -c 'cat > /etc/systemd/system/radar_bds.service <<EOF
[Unit]
Description=Gunicorn instance to serve Radar BDS
After=network.target

[Service]
User=$USER
Group=www-data
WorkingDirectory=/home/$USER/radar_bds
Environment="PATH=/home/$USER/radar_bds/venv/bin"
Environment="RADAR_DB_PATH=/home/$USER/radar_bds/radar_bds.db"
ExecStart=/home/$USER/radar_bds/venv/bin/gunicorn --workers 3 --bind unix:radar_bds.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
EOF'

# 6. Cấu hình Nginx làm Proxy ngược
sudo bash -c 'cat > /etc/nginx/sites-available/radar_bds <<EOF
server {
    listen 80;
    server_name _;

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/$USER/radar_bds/radar_bds.sock;
    }
}
EOF'

sudo ln -s /etc/nginx/sites-available/radar_bds /etc/nginx/sites-enabled
sudo nginx -t && sudo systemctl restart nginx

# 7. Mở Firewall trên Ubuntu (iptables)
sudo ufw allow 80
sudo ufw allow 443

echo "--- 📅 Thiết lập lịch chạy Crawler (Crontab) ---"
# Tự động chạy crawler lúc 10h tối (22h) mỗi ngày
(crontab -l 2>/dev/null; echo "0 22 * * * cd /home/$USER/radar_bds && /home/$USER/radar_bds/venv/bin/python run_all_crawlers.py") | crontab -

echo "--- ✅ Hoàn tất! Hãy copy code của anh vào /home/$USER/radar_bds ---"
echo "Sau đó chạy: sudo systemctl start radar_bds"
