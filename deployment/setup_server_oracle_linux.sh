#!/bin/bash

# Script setup server Oracle Linux 9 cho dự án Radar BDS
echo "--- 🚀 Bắt đầu thiết lập Server Radar BDS (Oracle Linux 9) ---"

# 1. Cập nhật hệ thống và cài đặt công cụ cơ bản
sudo dnf update -y
sudo dnf install -y python3 python3-pip nginx git sqlite curl

# 2. Mở cổng firewall trên máy (Oracle Linux dùng firewalld)
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# 3. Tạo thư mục dự án và môi trường ảo
mkdir -p ~/radar_bds
cd ~/radar_bds
python3 -m venv venv
source venv/bin/activate

# 4. Cài đặt các thư viện cần thiết
pip install --upgrade pip
pip install flask gunicorn pandas requests beautifulsoup4 playwright
playwright install chromium

# Cài đặt dependencies cho Playwright trên RHEL/Oracle Linux
sudo dnf install -y alsa-lib at-spi2-atk atk cups-libs dbus-libs expat \
    libX11 libXcomposite libXcursor libXdamage libXext libXfixes libXi \
    libXrender libXtst libXrandr libuuid pango mesa-libgbm

# 5. Cấu hình Gunicorn Service
sudo bash -c "cat > /etc/systemd/system/radar_bds.service <<EOF
[Unit]
Description=Gunicorn instance to serve Radar BDS
After=network.target

[Service]
User=$USER
Group=nginx
WorkingDirectory=/home/$USER/radar_bds
Environment=\"PATH=/home/$USER/radar_bds/venv/bin\"
Environment=\"RADAR_DB_PATH=/home/$USER/radar_bds/radar_bds.db\"
ExecStart=/home/$USER/radar_bds/venv/bin/gunicorn --workers 3 --bind unix:radar_bds.sock -m 007 app:app

[Install]
WantedBy=multi-user.target
EOF"

# 6. Cấu hình Nginx
sudo bash -c "cat > /etc/nginx/conf.d/radar_bds.conf <<EOF
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://unix:/home/$USER/radar_bds/radar_bds.sock;
        include proxy_params;
    }
}
EOF"

# Lưu ý: Oracle Linux có cấu hình SELinux khắt khe, ta cần tạm nới lỏng để Nginx truy cập được sock file
sudo setsebool -P httpd_can_network_connect 1
sudo chmod 755 /home/$USER

# 7. Khởi động các dịch vụ
sudo systemctl enable --now nginx
sudo systemctl enable --now radar_bds

# 8. Thiết lập Crontab (10h tối)
(crontab -l 2>/dev/null; echo "0 22 * * * cd /home/$USER/radar_bds && /home/$USER/radar_bds/venv/bin/python run_all_crawlers.py") | crontab -

echo "--- ✅ Hoàn tất thiết lập trên Oracle Linux 9! ---"
