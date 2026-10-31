"""Ephemeral, same-origin OCR of a cropped coordinate table, never a document store."""
import io
import os
import re
import shutil
import subprocess
import threading

from PIL import Image, ImageOps, UnidentifiedImageError

GATE = threading.BoundedSemaphore(1)
MAX_BYTES = 4_000_000


class OCRBusy(Exception):
    pass


class OCRUnavailable(Exception):
    pass


def number(value):
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+,\d{1,8}', value):
        value = value.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:,\d{3})+\.\d{1,8}', value):
        value = value.replace(',', '')
    elif re.fullmatch(r'\d{1,9}(?:[.,]\d{1,18})?', value):
        value = value.replace(',', '.')
    else:
        return None
    return value


def parse_coordinates(text, system):
    if system not in ('wgs84', 'vn2000') or not isinstance(text, str) or len(text) > 100000:
        raise ValueError('Invalid OCR input')
    rows, indices, skipped = [], [], 0
    for line in text.splitlines():
        if re.search(r'[A-Za-zÀ-ỹ]', line):
            if re.search(r'\d{5,}', line): skipped += 1
            continue
        tokens = re.findall(r'(?<![\w.])\d[\d.,]*(?![\w.])', line)
        values = [n for token in tokens if (n := number(token)) is not None]
        pair = None
        for index in range(len(values)-1):
            a, b = float(values[index]), float(values[index+1])
            valid = (6 <= a <= 25 and 100 <= b <= 112) if system == 'wgs84' else (
                100000 <= a <= 3000000 and 100000 <= b <= 900000)
            if valid:
                pair = ' '.join(values[index:index+2])
                if index == 1 and values[0].isdigit() and int(values[0]) <= 101:
                    indices.append(int(values[0]))
                break
        if pair:
            rows.append(pair)
        elif any(len(t) >= 5 for t in tokens):
            skipped += 1
    warnings = []
    if skipped or (indices and indices != list(range(1, len(indices)+1))):
        warnings.append('Có dòng không đọc được hoặc số thứ tự bị thiếu. Đối chiếu và bổ sung toàn bộ các góc từ ảnh.')
    if len(rows) > 100:
        rows = rows[:100]; warnings.append('Ảnh có hơn 100 dòng; chỉ giữ 100 dòng đầu để kiểm tra.')
    return dict(text='\n'.join(rows), count=len(rows), warnings=warnings)


def scan(payload, system):
    if system not in ('wgs84', 'vn2000') or not payload or len(payload) > MAX_BYTES:
        raise ValueError('Invalid image or coordinate system')
    if not GATE.acquire(blocking=False):
        raise OCRBusy()
    try:
        try:
            with Image.open(io.BytesIO(payload)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width*source.height > 8_000_000:
                    raise ValueError('Unsupported raster image')
                image = ImageOps.exif_transpose(source).convert('L')
            image.thumbnail((2400, 2400))
            image = ImageOps.autocontrast(image)
            normalized = io.BytesIO(); image.save(normalized, format='PNG')
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError('Invalid image') from exc
        executable = shutil.which('tesseract')
        if not executable:
            raise OCRUnavailable()
        try:
            result = subprocess.run([executable, 'stdin', 'stdout', '-l', 'eng', '--psm', '6',
                                     '-c', 'preserve_interword_spaces=1'], input=normalized.getvalue(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=20, env=dict(os.environ, OMP_THREAD_LIMIT='1'), check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OCRUnavailable() from exc
        if result.returncode or len(result.stdout) > 100000:
            raise OCRUnavailable()
        return parse_coordinates(result.stdout.decode('utf-8', errors='replace'), system)
    finally:
        GATE.release()
