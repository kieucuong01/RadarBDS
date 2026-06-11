from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps


DATA_IMAGES_DIR = Path(__file__).resolve().parent.parent / "data" / "images"
THUMB_DIR = DATA_IMAGES_DIR / "thumbs"
THUMB_MAX_SIZE = (520, 338)
THUMB_QUALITY = 62
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def normalize_image_url(src: str) -> str:
    if not src:
        return ""
    s = str(src).strip().replace("\\", "/")
    if not s or s.upper().endswith("NOT_FOUND"):
        return ""
    if s.startswith(("http://", "https://", "data:")):
        return s
    if s.startswith("/data/images/"):
        return s
    marker = "data/images/"
    if marker in s:
        return "/" + s[s.index(marker):]
    return "/data/images/" + Path(s).name


@lru_cache(maxsize=30000)
def local_image_exists(url: str) -> bool:
    path = local_path_for_url(url)
    return bool(path and path.exists())


def local_path_for_url(url: str) -> Optional[Path]:
    normalized = normalize_image_url(url)
    if not normalized.startswith("/data/images/"):
        return None
    rel = normalized.removeprefix("/data/images/")
    return DATA_IMAGES_DIR / rel


def thumb_path_for_image(image_path: Path) -> Path:
    return THUMB_DIR / f"{image_path.stem}.webp"


def thumb_url_for_image_url(url: str) -> str:
    image_path = local_path_for_url(url)
    if not image_path:
        return ""
    thumb_path = thumb_path_for_image(image_path)
    if not thumb_path.exists():
        return ""
    return f"/data/images/thumbs/{thumb_path.name}"


def ensure_thumbnail(image_path: Path, force: bool = False) -> Optional[Path]:
    if not image_path or image_path.suffix.lower() not in IMAGE_EXTS:
        return None
    if "thumbs" in image_path.parts:
        return None
    if not image_path.exists() or image_path.stat().st_size <= 0:
        return None

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_path_for_image(image_path)
    if thumb_path.exists() and not force:
        return thumb_path

    with Image.open(image_path) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail(THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        img.save(thumb_path, "WEBP", quality=THUMB_QUALITY, method=6)
    local_image_exists.cache_clear()
    return thumb_path


def resolve_image_url(local_src: str, remote_src: str = "", prefer_thumb: bool = False) -> str:
    local_url = normalize_image_url(local_src)
    if local_url and prefer_thumb:
        thumb_url = thumb_url_for_image_url(local_url)
        if thumb_url:
            return thumb_url
    if local_url and local_image_exists(local_url):
        if prefer_thumb:
            thumb_url = thumb_url_for_image_url(local_url)
            if thumb_url:
                return thumb_url
        return local_url
    remote_url = normalize_image_url(remote_src)
    if remote_url:
        return remote_url
    return local_url
