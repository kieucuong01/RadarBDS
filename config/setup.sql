-- Chạy lần đầu để tạo database
-- psql -U postgres -f setup.sql

CREATE DATABASE radar_bds
    WITH ENCODING 'UTF8'
    LC_COLLATE 'vi_VN.UTF-8'
    LC_CTYPE   'vi_VN.UTF-8'
    TEMPLATE template0;

-- Nếu locale vi_VN không có, dùng:
-- CREATE DATABASE radar_bds WITH ENCODING 'UTF8';

\connect radar_bds

-- Extension cho tìm kiếm full-text tiếng Việt (tùy chọn)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- Extension geospatial (tùy chọn, nếu cần overlay map sau)
-- CREATE EXTENSION IF NOT EXISTS postgis;
