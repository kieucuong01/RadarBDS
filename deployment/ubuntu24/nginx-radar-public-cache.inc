proxy_pass http://radar_bds_app;
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Connection "";

proxy_cache radar_public;
proxy_cache_methods GET HEAD;
proxy_cache_key "$scheme$request_method$host$request_uri";
proxy_cache_bypass $radar_has_session $http_authorization;
proxy_no_cache $radar_has_session $http_authorization $radar_not_app_public $upstream_http_set_cookie;
proxy_cache_valid 200 15s;
proxy_cache_lock on;
proxy_cache_lock_timeout 10s;
proxy_cache_lock_age 10s;
proxy_cache_background_update on;
proxy_cache_use_stale updating;

proxy_connect_timeout 2s;
proxy_read_timeout 10s;
proxy_send_timeout 10s;
proxy_hide_header X-Radar-Public-Cache;
