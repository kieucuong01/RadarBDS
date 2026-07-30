from crawler.guland_pw import extract_guland_image_urls_from_dom_candidates


def test_extract_guland_images_keeps_css_background_urls_for_same_post():
    urls = extract_guland_image_urls_from_dom_candidates(
        "https://guland.vn/post/ban-nha-hiep-thanh-2547279",
        [
            "data:image/gif;base64,placeholder",
            "/bds_2/img/logo-guland.webp",
            "https://bizcdn.guland.vn/images/posts/2547279/detail/pi-13038671-1280.webp",
            "https://bizcdn.guland.vn/images/posts/2547279/listing/pi-13038671-720.webp",
            "https://bizcdn.guland.vn/images/posts/2551413/listing/pi-13059005-720.webp",
            "https://bizcdn.guland.vn/users/image/avatar-op.webp",
            "https://datacdn.guland.vn/data/2547279/20260730_2547279_0.jpg",
        ],
    )

    assert urls == [
        "https://bizcdn.guland.vn/images/posts/2547279/detail/pi-13038671-1280.webp",
        "https://datacdn.guland.vn/data/2547279/20260730_2547279_0.jpg",
    ]


def test_extract_guland_images_dedupes_and_rejects_related_listing_images():
    urls = extract_guland_image_urls_from_dom_candidates(
        "https://guland.vn/post/ban-dat-2551373",
        [
            "https://bizcdn.guland.vn/images/posts/2551373/detail/pi-13058803-1280.webp",
            "https://bizcdn.guland.vn/images/posts/2551373/detail/pi-13058803-1280.webp",
            "https://bizcdn.guland.vn/images/posts/1283017/listing/pi-5784069-720.webp",
        ],
    )

    assert urls == [
        "https://bizcdn.guland.vn/images/posts/2551373/detail/pi-13058803-1280.webp",
    ]
