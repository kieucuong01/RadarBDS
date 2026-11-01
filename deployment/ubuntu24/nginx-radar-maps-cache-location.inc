# Optional origin offload for public geometry only. Include inside the HTTPS server.
# Requires radar_maps zone from nginx-radar-maps-cache.conf (http context).
location ~ "^/api/planning/(parcel-cells/[a-f0-9]{16}/(snapshot|live)/[0-9]{1,6}/[0-9]{1,6}[.]json|gis-tiles/(partition|urban_general|detailed)/[0-9]{1,2}/[0-9]{1,8}/[0-9]{1,8}[.]png)$" {
    proxy_pass http://radar_bds_app;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_cache radar_maps;
    proxy_cache_methods GET HEAD;
    proxy_cache_key "$scheme|$host|$request_uri";
    proxy_cache_bypass $http_cookie $http_authorization;
    proxy_no_cache $http_cookie $http_authorization $upstream_http_set_cookie;
    # Keep the application's Cache-Control/Vary. Never ignore private/no-store.
    proxy_cache_valid 200 5m;
    proxy_cache_lock on;
    proxy_cache_lock_timeout 5s;
    proxy_cache_lock_age 30s;
    proxy_read_timeout 45s;
}
