#!/usr/bin/env python3
"""Publish native Radar BDS Facebook Page-care posts.

This is intentionally deterministic and cron-safe. It does not use passwords,
cookies, paid APIs, or LLM calls. It rotates practical buyer-facing content
pillars so the Page is not only link/data reposts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path("/opt/radar-bds/current")
POST_SCRIPT = REPO / "scripts/browser_use_page_post.py"
START_BROWSER = Path("/home/hermesops/radar-browser-use/start-radar-social-browser.sh")
CDP_URL = "http://127.0.0.1:9224"
QUEUE_DIR = Path("/opt/radar-bds/var/social_queue/page_care")
STATE_PATH = QUEUE_DIR / "posted_native.json"
RUN_DIR = Path("/opt/radar-bds/var/browser_use_runs")
PAGE_URL = "https://www.facebook.com/radarbdsvn/"

FORBIDDEN = [
    "deal ngon",
    "lời chắc",
    "cam kết lợi nhuận",
    "sinh lời",
    "cơ hội vàng",
    "rẻ nhất",
    "dưới giá thị trường",
    "hot nhất",
    "sốt đất",
    "pháp lý chuẩn 100%",
]

MORNING_POSTS: list[dict[str, str]] = [
    {
        "id": "checklist-before-calling",
        "pillar": "checklist",
        "message": """
        Trước khi gọi một tin đất, anh chị nên kiểm tra nhanh 5 dòng:

        1. Phường/khu cụ thể ở đâu?
        2. Diện tích bao nhiêu m²?
        3. Giá tổng bao nhiêu tỷ?
        4. Giá/m² khoảng bao nhiêu?
        5. Là đất nền, nhà đất hay loại hình khác?

        Thiếu 2/5 dòng này thì nên hỏi kỹ trước khi mất thời gian đi xem.
        """,
    },
    {
        "id": "cheap-not-always-deal",
        "pillar": "canh_bao",
        "message": """
        Một tin rao rẻ hơn khu vực chưa chắc là tin tốt.

        Có thể rẻ vì đường nhỏ hơn, vị trí khó đi hơn, pháp lý cần kiểm tra thêm, hoặc chỉ là tin kéo inbox.

        Khi thấy giá thấp bất thường, việc đầu tiên không phải là mừng, mà là so với vài tin cùng phường, cùng loại hình.
        """,
    },
    {
        "id": "price-per-m2-context",
        "pillar": "giai_thich",
        "message": """
        Giá/m² chỉ có ý nghĩa khi đặt đúng bối cảnh.

        Cùng một mức 25 triệu/m² nhưng đất nền, nhà đất, hẻm nhỏ, mặt tiền, diện tích lớn/nhỏ sẽ rất khác nhau.

        Vì vậy Radar BDS luôn cố tách theo loại hình trước khi so giá.
        """,
    },
    {
        "id": "broker-source-quality",
        "pillar": "nguon_tin",
        "message": """
        Một nguồn tin đáng theo dõi thường có đặc điểm:

        • ghi rõ giá và diện tích
        • tập trung một vài khu vực quen
        • ảnh/thông tin nhất quán
        • không đổi nội dung quá mập mờ

        Người mua nên xem chất lượng nguồn tin, không chỉ xem giá rao.
        """,
    },
    {
        "id": "median-price-explain",
        "pillar": "giai_thich",
        "message": """
        “Giá trung vị” nghĩa là gì?

        Nói đơn giản: một nửa số tin rao thấp hơn mức đó, một nửa cao hơn mức đó.

        Radar BDS dùng giá trung vị để tránh bị một vài tin giá quá cao/quá thấp làm lệch cách nhìn thị trường.
        """,
    },
    {
        "id": "land-vs-house",
        "pillar": "giai_thich",
        "message": """
        Đừng so đất nền và nhà đất bằng một con số chung.

        Nhà đất thường đã có tài sản trên đất, hiện trạng xây dựng và khả năng vào ở/cho thuê.
        Đất nền lại phụ thuộc nhiều vào vị trí, đường, pháp lý và khả năng xây dựng.

        So sai loại hình thì rất dễ hiểu sai giá.
        """,
    },
    {
        "id": "before-viewing-land",
        "pillar": "checklist",
        "message": """
        Trước khi đi xem đất, nên lưu lại ít nhất 3 tin tương tự cùng khu.

        Khi đó anh chị sẽ dễ hỏi hơn:
        • vì sao tin này cao hơn?
        • vì sao tin kia thấp hơn?
        • khác nhau ở đường, pháp lý, diện tích hay vị trí?

        Đi xem đất mà không có mốc so sánh rất dễ bị neo giá.
        """,
    },
    {
        "id": "inbox-price-warning",
        "pillar": "canh_bao",
        "message": """
        Tin rao ghi “giá tốt, inbox” không hẳn là xấu, nhưng nên cẩn thận.

        Người mua nên hỏi thẳng 3 thông tin trước:
        1. Giá tổng?
        2. Diện tích?
        3. Phường/khu cụ thể?

        Nếu vẫn vòng vo, anh chị nên ưu tiên tin minh bạch hơn.
        """,
    },
    {
        "id": "road-width-question",
        "pillar": "kinh_nghiem",
        "message": """
        Khi xem đất hẻm, đừng chỉ hỏi “hẻm mấy mét”.

        Nên hỏi thêm:
        • xe hơi vào được không?
        • có quay đầu được không?
        • hẻm thông hay cụt?
        • đường thực tế có giống mô tả không?

        Nhiều tin rao đúng giá nhưng thiếu bối cảnh đường/hẻm.
        """,
    },
    {
        "id": "radar-role",
        "pillar": "behind_the_scenes",
        "message": """
        Radar BDS không thay anh chị đi xem đất, cũng không thay thẩm định pháp lý.

        Vai trò của Radar là lọc dữ liệu ban đầu: giá, diện tích, khu vực, loại hình và dấu hiệu cần kiểm tra.

        Mục tiêu là giúp người mua bớt mất thời gian với tin thiếu thông tin.
        """,
    },
    {
        "id": "same-area-price-diff",
        "pillar": "mini_case",
        "message": """
        Cùng một phường, hai tin rao có thể lệch rất xa.

        Lý do thường nằm ở: đường/hẻm, diện tích, hình dạng đất, pháp lý, hiện trạng nhà, hoặc khoảng cách tới trục chính.

        Vì vậy câu hỏi hay không phải là “khu này giá bao nhiêu”, mà là “tin này đang giống nhóm nào trong khu đó”.
        """,
    },
    {
        "id": "price-drop-check",
        "pillar": "canh_bao",
        "message": """
        Thấy tin giảm giá, nên hỏi thêm:

        • giảm từ mức nào?
        • giảm từ khi nào?
        • có thay đổi pháp lý/vị trí/thông tin không?
        • cùng khu có tin nào tương tự không?

        Giảm giá là dấu hiệu đáng xem, nhưng không phải kết luận cuối cùng.
        """,
    },
    {
        "id": "local-demand-question",
        "pillar": "hoi_dap",
        "message": """
        Anh chị đang quan tâm khu nào ở Bình Dương nhất hiện tại?

        A. Thủ Dầu Một
        B. Dĩ An
        C. Thuận An
        D. Bến Cát / Tân Uyên

        Radar sẽ ưu tiên làm nội dung khu vực có nhiều người cần theo dõi trước.
        """,
    },
    {
        "id": "transparent-listing",
        "pillar": "kinh_nghiem",
        "message": """
        Một tin rao dễ kiểm tra thường có đủ:

        • giá tổng
        • diện tích
        • phường/khu
        • loại hình: đất nền hay nhà đất
        • vài mô tả về đường/pháp lý

        Tin càng rõ, người mua càng dễ so sánh và đặt câu hỏi đúng.
        """,
    },
]

EVENING_POSTS: list[dict[str, str]] = [
    {
        "id": "poll-2-5b-choice",
        "pillar": "tuong_tac",
        "message": """
        Nếu có khoảng 2,5 tỷ ở Bình Dương, anh chị sẽ ưu tiên gì?

        A. Đất nền khu xa hơn, diện tích rộng hơn
        B. Nhà cũ khu đông dân, vào ở được
        C. Chờ thêm để chọn vị trí tốt hơn

        Mỗi lựa chọn sẽ có cách lọc tin khác nhau.
        """,
    },
    {
        "id": "poll-land-or-house",
        "pillar": "tuong_tac",
        "message": """
        Cùng ngân sách, anh chị thấy phương án nào dễ quyết hơn?

        A. Đất nền: tự tính chuyện xây sau
        B. Nhà đất: có thể dùng/cho thuê sớm

        Radar hỏi để hiểu nhu cầu người mua thật, không phải tư vấn mua bán.
        """,
    },
    {
        "id": "question-low-price-threshold",
        "pillar": "tuong_tac",
        "message": """
        Một tin rao thấp hơn mặt bằng khu vực bao nhiêu thì anh chị bắt đầu nghi ngờ?

        A. 5–10%
        B. 10–20%
        C. Trên 20%
        D. Cứ rẻ là phải kiểm tra ngay

        Với Radar, giá thấp là tín hiệu để xem kỹ hơn, không phải kết luận “deal”.
        """,
    },
    {
        "id": "question-inbox-price",
        "pillar": "tuong_tac",
        "message": """
        Anh chị có hay bỏ qua tin rao ghi “inbox giá” không?

        A. Bỏ qua luôn
        B. Vẫn hỏi nếu vị trí tốt
        C. Tùy người đăng

        Với người mua bận rộn, tin thiếu giá thường làm tăng chi phí thời gian.
        """,
    },
    {
        "id": "mini-case-80m2",
        "pillar": "mini_case",
        "message": """
        Cùng 80m² nhưng một tin có thể 2,1 tỷ, tin khác 3,4 tỷ.

        Trước khi kết luận tin nào đắt/rẻ, nên tách 4 thứ:
        đường, pháp lý, vị trí trong phường, và loại hình tài sản.

        Một con số giá tổng chưa đủ để so.
        """,
    },
    {
        "id": "buyer-mistake-one-number",
        "pillar": "canh_bao",
        "message": """
        Sai lầm phổ biến khi xem giá đất: hỏi “khu này bao nhiêu một mét?” rồi lấy một con số để so tất cả.

        Thị trường thật có nhiều lớp: đất nền/nhà đất, hẻm/mặt tiền, diện tích nhỏ/lớn, pháp lý rõ/chưa rõ.

        Càng tách đúng nhóm, càng đỡ bị nhiễu.
        """,
    },
    {
        "id": "question-ward-focus",
        "pillar": "tuong_tac",
        "message": """
        Nếu Radar làm bảng theo dõi hằng tuần, anh chị muốn xem khu nào trước?

        A. Dĩ An
        B. Thuận An
        C. Thủ Dầu Một
        D. Bến Cát / Tân Uyên

        Comment khu vực cụ thể, Radar sẽ ưu tiên nơi có nhu cầu cao.
        """,
    },
    {
        "id": "legal-soft-reminder",
        "pillar": "phap_ly_mem",
        "message": """
        Ảnh sổ trong tin rao giúp người mua có thêm thông tin, nhưng chưa đủ để kết luận an toàn.

        Khi đi sâu hơn vẫn cần kiểm tra quy hoạch, hiện trạng, chủ sở hữu, nghĩa vụ tài chính và thông tin tại cơ quan/chuyên gia phù hợp.

        Radar chỉ hỗ trợ lọc bước đầu.
        """,
    },
    {
        "id": "broker-consistency",
        "pillar": "nguon_tin",
        "message": """
        Một môi giới đăng đều trong một khu quen thường dễ kiểm tra hơn người đăng rải quá nhiều nơi.

        Nhưng vẫn cần nhìn từng tin: giá, diện tích, vị trí, ảnh và mức độ minh bạch.

        Radar đang ưu tiên lọc nguồn tin theo chất lượng dữ liệu, không chỉ theo số lượng bài đăng.
        """,
    },
    {
        "id": "save-time-angle",
        "pillar": "gia_tri_radar",
        "message": """
        Người mua mất thời gian nhất ở bước nào?

        Theo Radar, thường là bước lọc tin ban đầu: tin thiếu giá, thiếu diện tích, vị trí mơ hồ, hoặc không rõ loại hình.

        Lọc kỹ từ đầu giúp ít phải gọi những tin không phù hợp.
        """,
    },
    {
        "id": "question-rent-or-hold",
        "pillar": "tuong_tac",
        "message": """
        Mua BĐS ở Bình Dương, anh chị nghiêng về mục tiêu nào hơn?

        A. Ở thật
        B. Cho thuê/dòng tiền
        C. Giữ tài sản dài hạn
        D. Lướt sóng thì không ưu tiên

        Mục tiêu khác nhau thì cách lọc tin cũng khác nhau.
        """,
    },
    {
        "id": "red-flag-missing-area",
        "pillar": "canh_bao",
        "message": """
        Tin rao có giá tổng nhưng thiếu diện tích là tin khó so sánh.

        Vì không có diện tích thì không tính được giá/m², cũng khó đặt cạnh các tin cùng khu.

        Nếu người đăng không bổ sung được thông tin cơ bản, anh chị nên cân nhắc ưu tiên tin minh bạch hơn.
        """,
    },
    {
        "id": "simple-data-promise",
        "pillar": "behind_the_scenes",
        "message": """
        Radar BDS cố giữ một nguyên tắc đơn giản:

        Không nói thị trường bằng cảm giác nếu có thể kiểm tra bằng dữ liệu.

        Nhưng dữ liệu tin rao vẫn chỉ là bước đầu. Khi xuống tiền, người mua vẫn cần kiểm tra pháp lý, quy hoạch và hiện trạng thực tế.
        """,
    },
    {
        "id": "weekend-light-question",
        "pillar": "tuong_tac",
        "message": """
        Nếu cuối tuần đi xem đất, anh chị thường xem mấy tin trong một buổi?

        A. 1–2 tin cho kỹ
        B. 3–5 tin để so nhanh
        C. Càng nhiều càng tốt

        Radar nghiêng về cách chọn ít tin hơn nhưng lọc kỹ hơn trước khi đi.
        """,
    },
]


def log(message: str) -> None:
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def cdp_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=4) as resp:  # noqa: S310 - localhost only
            return resp.status == 200
    except Exception:
        return False


def ensure_browser() -> None:
    if cdp_ready():
        log("Chrome CDP already reachable at 127.0.0.1:9224")
        return
    if not START_BROWSER.exists():
        raise SystemExit(f"Browser start script missing: {START_BROWSER}")
    log("Starting dedicated Radar Social Chrome worker")
    subprocess.Popen(
        [str(START_BROWSER)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(REPO),
    )
    for _ in range(30):
        time.sleep(1)
        if cdp_ready():
            log("Chrome CDP is ready")
            return
    raise SystemExit("Chrome CDP did not become ready within 30s")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"posted": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"posted": {}}


def save_state(state: dict[str, Any]) -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def clean_message(text: str) -> str:
    message = textwrap.dedent(text).strip()
    message = "\n".join(line.rstrip() for line in message.splitlines())
    lowered = message.casefold()
    hits = [x for x in FORBIDDEN if x.casefold() in lowered]
    if hits:
        raise SystemExit(f"Forbidden marketing claim(s) in native post: {', '.join(hits)}")
    if len(message) > 1200:
        raise SystemExit(f"Native post too long: {len(message)} chars")
    return message


def choose_item(slot: str, date: dt.date) -> dict[str, str]:
    pool = MORNING_POSTS if slot == "morning" else EVENING_POSTS
    # Deterministic rotation; offset evening so the two daily posts do not share cadence.
    offset = 0 if slot == "morning" else 5
    idx = (date.toordinal() + offset) % len(pool)
    return pool[idx]


def create_queue(slot: str, date: dt.date, item: dict[str, str], mode: str) -> Path:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    key = f"native-{slot}-{item['id']}"
    path = QUEUE_DIR / f"{date.isoformat()}-{slot}-{item['id']}.json"
    payload = {
        "schema": "radar_social_queue.v1",
        "created_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "target": {"platform": "facebook_page", "page_url": PAGE_URL},
        "source": {"slug": key, "article_date": date.isoformat(), "url": ""},
        "content": {
            "format": "native_page_care",
            "pillar": item["pillar"],
            "message": clean_message(item["message"]),
        },
        "selection": {
            "slot": slot,
            "rule": "rotate native pillars; avoid link-only/data-only Page; use buyer pain, legal/data literacy, and engagement questions",
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"Queue created: {path}")
    return path


def publish(queue_path: Path) -> dict[str, Any]:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [str(POST_SCRIPT), "--queue", str(queue_path), "--mode", "publish", "--yes", "--timeout", "240"]
    proc = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=320, check=False)
    record = {"returncode": proc.returncode, "stdout_tail": proc.stdout[-3000:], "stderr_tail": proc.stderr[-3000:]}
    if proc.returncode != 0:
        raise SystemExit(
            "Facebook Page native publish failed\n"
            f"STDOUT:\n{proc.stdout[-3000:]}\nSTDERR:\n{proc.stderr[-3000:]}"
        )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish Radar BDS native Page-care post")
    parser.add_argument("--slot", choices=["morning", "evening"], required=True)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    os.chdir(REPO)
    date = dt.date.fromisoformat(args.date)
    item = choose_item(args.slot, date)
    key = f"{date.isoformat()}:{args.slot}:native-{args.slot}-{item['id']}"
    queue_path = create_queue(args.slot, date, item, "prepare" if args.dry_run else "publish")

    state = load_state()
    posted = state.setdefault("posted", {})
    if key in posted:
        log(f"SKIP: already posted {key} at {posted[key].get('posted_at')}")
        print(f"@rb native Page-care skipped: already posted `{item['id']}`")
        return 0

    if args.dry_run:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        print(json.dumps({"ok": True, "key": key, "queue": str(queue_path), "pillar": item["pillar"], "message": data["content"]["message"]}, ensure_ascii=False, indent=2))
        return 0

    ensure_browser()
    log(f"Publishing native Page-care item: {key}")
    result = publish(queue_path)
    posted[key] = {
        "slot": args.slot,
        "slug": f"native-{args.slot}-{item['id']}",
        "pillar": item["pillar"],
        "queue": str(queue_path),
        "posted_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "result": result,
    }
    save_state(state)
    print("@rb native Page-care post OK")
    print(f"Slot: {args.slot}")
    print(f"Pillar: {item['pillar']}")
    print(f"Queue: {queue_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
