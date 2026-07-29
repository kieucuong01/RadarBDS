"""Anonymous PayOS checkout routes for protected digital products."""

from __future__ import annotations

import base64
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import quote

import qrcode
import qrcode.image.svg
from flask import (
    Blueprint,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
)
from itsdangerous import BadData, URLSafeTimedSerializer

from auth.core import rate_limit
from config.settings import (
    PUBLIC_BASE_URL,
    get_digital_product_commerce_settings,
)
from db.connection import AdvisoryLockBusy, advisory_lock
from services.digital_product_orders import (
    InvalidSettlement,
    OrderLifecycleError,
    PostgresOrderRepository,
    SettlementNotFound,
    attach_payment_link,
    can_download,
    create_pending_order,
    expire_pending_order,
    get_order,
    record_download,
    settle_verified_payment,
    verify_recovery_token,
)
from services.digital_products import (
    ProtectedPackageUnavailable,
    get_digital_product,
    get_release_availability,
    snapshot_protected_package,
)
from services.payos_client import (
    PayOSClient,
    PayOSClientError,
    PayOSWebhookRejected,
)


bp = Blueprint("digital_products", __name__)

_PRODUCT_SLUG = "thu-dau-mot-map-bundle"
_ORDER_COOKIE = "radar_product_order"
_RETRY_COOKIE = "radar_product_checkout_retry"
_ORDER_COOKIE_MAX_AGE = 90_000
_RETRY_COOKIE_MAX_AGE = 300
_ORDER_COOKIE_SALT = "radar-digital-product-order-v1"
_RETRY_COOKIE_SALT = "radar-digital-product-retry-v1"
_PUBLIC_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_BASE36_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_MAX_AUTHORIZE_BODY_BYTES = 2 * 1_024
_MAX_WEBHOOK_BODY_BYTES = 64 * 1_024


def _repository_factory():
    return PostgresOrderRepository()


def _payos_client_factory():
    return PayOSClient()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def _checkout_lock_factory(public_id: str):
    with advisory_lock(
        f"digital-product-checkout:{public_id}",
        wait=False,
    ):
        yield


def _impl(name: str, **kwargs):
    import app as app_module

    return getattr(app_module, name)(**kwargs)


@bp.get("/ban-do-thu-dau-mot")
def thu_dau_mot_map_product_page(**kwargs):
    response = make_response(
        _impl("thu_dau_mot_map_product_page", **kwargs)
    )
    settings = get_digital_product_commerce_settings()
    if (
        _valid_cookie_secret(settings.cookie_secret)
        and _retry_state(settings.cookie_secret) is None
    ):
        _set_retry_cookie(
            response,
            _signed_retry_state(
                settings.cookie_secret,
                uuid.uuid4().hex,
                "seed",
            ),
        )
    return response


@bp.post("/ban-do-thu-dau-mot/checkout")
@rate_limit(
    "digital_product_checkout",
    limits={"guest": 10, "free": 10, "vip": 10, "admin": 30},
)
def checkout_thu_dau_mot_map():
    settings = get_digital_product_commerce_settings()
    product = get_digital_product(_PRODUCT_SLUG)
    if not settings.ready_for_checkout or settings.storage_dir is None:
        return jsonify({"code": "product_unavailable"}), 503
    availability = get_release_availability(
        product,
        settings.storage_dir,
        settings.sales_enabled,
    )
    if not availability.can_sell:
        return jsonify({"code": "product_unavailable"}), 503

    now = _utcnow()
    retry_state = _retry_state(settings.cookie_secret)
    if retry_state is None:
        retry_state = {
            "public_id": uuid.uuid4().hex,
            "phase": "seed",
        }
    public_id = retry_state["public_id"]
    retry_seed = _signed_retry_state(
        settings.cookie_secret,
        public_id,
        "seed",
    )
    repo = _repository_factory()
    try:
        with _checkout_lock_factory(public_id):
            order = get_order(public_id, repo=repo)
            if order is None:
                order = create_pending_order(
                    product,
                    now,
                    public_id=public_id,
                    repo=repo,
                )
            elif (
                order.status != "pending"
                or now >= order.payment_expires_at
            ):
                return _checkout_in_progress_response(
                    settings.cookie_secret,
                    public_id,
                )

            complete_link = _has_complete_payment_link(order)
            if _has_any_payment_link(order) and not complete_link:
                raise OrderLifecycleError("incomplete payment link metadata")
            if retry_state["phase"] == "seed" and complete_link:
                return _checkout_in_progress_response(
                    settings.cookie_secret,
                    public_id,
                )

            order_url = (
                f"{PUBLIC_BASE_URL}/ban-do-thu-dau-mot/don-hang/"
                f"{order.public_id}"
            )
            if complete_link:
                payment_link = SimpleNamespace(
                    payment_link_id=order.payment_link_id,
                    checkout_url=order.checkout_url,
                    qr_payload=order.qr_code,
                )
            else:
                payment_link = _payos_client_factory().create_payment_link(
                    order,
                    order_url,
                    order_url,
                )
            pending_secret = attach_payment_link(
                order.public_id,
                payment_link,
                repo=repo,
            )
    except (OrderLifecycleError, PayOSClientError):
        if "order" in locals():
            _record_payment_link_failure(repo, order, now)
        response = jsonify({"code": "checkout_temporarily_unavailable"})
        response.status_code = 502
        _set_retry_cookie(response, retry_seed)
        return response
    except AdvisoryLockBusy:
        return _checkout_in_progress_response(
            settings.cookie_secret,
            public_id,
            phase=retry_state["phase"],
        )
    except Exception:
        response = jsonify({"code": "checkout_temporarily_unavailable"})
        response.status_code = 503
        _set_retry_cookie(response, retry_seed)
        return response

    fragment_token = quote(
        pending_secret.raw_recovery_token,
        safe="",
    )
    response = redirect(
        (
            f"/ban-do-thu-dau-mot/don-hang/"
            f"{pending_secret.order.public_id}#token={fragment_token}"
        ),
        code=303,
    )
    _set_retry_cookie(
        response,
        _signed_retry_state(
            settings.cookie_secret,
            pending_secret.order.public_id,
            "linked",
        ),
    )
    return response


@bp.get("/ban-do-thu-dau-mot/don-hang/<public_id>")
def thu_dau_mot_map_order_page(public_id: str):
    page = {"local_links": []}
    if _PUBLIC_ID_PATTERN.fullmatch(public_id or "") is None:
        return render_template(
            "thu_dau_mot_map_order.html",
            public_id="",
            page=page,
            active_nav="ban-do-binh-duong",
        ), 404
    return render_template(
        "thu_dau_mot_map_order.html",
        public_id=public_id,
        page=page,
        active_nav="ban-do-binh-duong",
    )


@bp.post("/api/digital-products/orders/<public_id>/authorize")
@rate_limit(
    "digital_product_order_authorize",
    limits={"guest": 30, "free": 30, "vip": 30, "admin": 30},
)
def authorize_digital_product_order(public_id: str):
    not_found = (jsonify({"code": "order_not_found"}), 404)
    if _PUBLIC_ID_PATTERN.fullmatch(public_id or "") is None:
        return not_found
    if (
        request.mimetype != "application/json"
        or (
            request.content_length is not None
            and request.content_length > _MAX_AUTHORIZE_BODY_BYTES
        )
    ):
        return not_found
    raw_body = request.stream.read(_MAX_AUTHORIZE_BODY_BYTES + 1)
    if not raw_body or len(raw_body) > _MAX_AUTHORIZE_BODY_BYTES:
        return not_found
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return not_found
    if type(payload) is not dict or set(payload) != {"token"}:
        return not_found
    token = payload.get("token")
    if type(token) is not str or not token or len(token) > 512:
        return not_found

    settings = get_digital_product_commerce_settings()
    if not _valid_cookie_secret(settings.cookie_secret):
        return not_found
    repo = _repository_factory()
    order = verify_recovery_token(
        public_id,
        token,
        now=_utcnow(),
        repo=repo,
    )
    if order is None:
        return not_found

    serializer = _order_serializer(settings.cookie_secret)
    response = make_response("", 204)
    response.set_cookie(
        _ORDER_COOKIE,
        serializer.dumps({"public_id": public_id}),
        max_age=_ORDER_COOKIE_MAX_AGE,
        httponly=True,
        secure=PUBLIC_BASE_URL.startswith("https://"),
        samesite="Lax",
        path=_order_cookie_path(public_id),
    )
    return response


@bp.get("/api/digital-products/orders/<public_id>/status")
@rate_limit(
    "digital_product_order_status",
    limits={"guest": 240, "free": 240, "vip": 240, "admin": 240},
)
def digital_product_order_status(public_id: str):
    order = _cookie_authorized_order(public_id)
    if order is None:
        return _order_not_found_response()

    now = _utcnow()
    repo = _repository_factory()
    if order.status == "pending":
        try:
            order = expire_pending_order(public_id, now, repo=repo)
        except OrderLifecycleError:
            return _order_not_found_response()
    qr_data_uri = None
    if order.status == "pending" and order.qr_code:
        qr_data_uri = _qr_svg_data_uri(order.qr_code)
    download_url = None
    if (
        order.status == "paid"
        and order.download_expires_at is not None
        and now < order.download_expires_at
    ):
        download_url = (
            f"/api/digital-products/orders/{public_id}/download"
        )
    payload = {
        "status": order.status,
        "amount_vnd": order.expected_amount,
        "payment_expires_at": _iso_datetime(order.payment_expires_at),
        "download_expires_at": _iso_datetime(order.download_expires_at),
        "qr_svg_data_uri": qr_data_uri,
        "order_label": _order_label(order.payos_order_code),
        "download_url": download_url,
    }
    response = jsonify(payload)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.get("/api/digital-products/orders/<public_id>/download")
@rate_limit(
    "digital_product_order_download",
    limits={"guest": 30, "free": 30, "vip": 30, "admin": 30},
)
def download_digital_product_order(public_id: str):
    order = _cookie_authorized_order(public_id)
    if order is None:
        return _download_denied_response()

    now = _utcnow()
    if (
        order.status == "paid"
        and order.download_expires_at is not None
        and now >= order.download_expires_at
    ):
        return _download_expired_response()
    if not can_download(order, now):
        return _download_denied_response()

    settings = get_digital_product_commerce_settings()
    if settings.storage_dir is None:
        return _download_unavailable_response()
    try:
        product = get_digital_product(_PRODUCT_SLUG)
        if (
            order.product_slug != product.slug
            or order.product_version != product.version
            or order.expected_amount != product.price_vnd
            or order.currency != "VND"
        ):
            return _download_denied_response()
        package_snapshot = snapshot_protected_package(
            product,
            settings.storage_dir,
        )
        response = send_file(
            package_snapshot.open_bytes_io(),
            mimetype="application/zip",
            as_attachment=True,
            download_name=product.download_filename,
            conditional=True,
            etag=package_snapshot.sha256,
            max_age=0,
        )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if response.status_code in {200, 206}:
            record_download(
                order.id,
                now,
                repo=_repository_factory(),
            )
        return response
    except ProtectedPackageUnavailable:
        return _download_unavailable_response()
    except Exception:
        return _download_unavailable_response()


@bp.post("/api/webhooks/payos/digital-products")
def payos_digital_products_webhook():
    if (
        request.content_length is not None
        and request.content_length > _MAX_WEBHOOK_BODY_BYTES
    ):
        return jsonify({"success": False}), 400
    raw_body = request.stream.read(_MAX_WEBHOOK_BODY_BYTES + 1)
    if len(raw_body) > _MAX_WEBHOOK_BODY_BYTES:
        return jsonify({"success": False}), 400
    try:
        verified = _payos_client_factory().verify_webhook(raw_body)
        settle_verified_payment(
            verified.order_code,
            verified.amount,
            verified.reference,
            verified.paid_at,
            verified.payload_hash,
            repo=_repository_factory(),
        )
    except SettlementNotFound:
        return jsonify({"success": False}), 404
    except (InvalidSettlement, PayOSWebhookRejected, PayOSClientError):
        return jsonify({"success": False}), 400
    except OrderLifecycleError:
        return jsonify({"success": False}), 400
    return jsonify({"success": True}), 200


def _retry_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        secret,
        salt=_RETRY_COOKIE_SALT,
    )


def _order_serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        secret,
        salt=_ORDER_COOKIE_SALT,
    )


def _retry_state(secret: str) -> dict[str, str] | None:
    signed = request.cookies.get(_RETRY_COOKIE)
    if not signed:
        return None
    try:
        payload = _retry_serializer(secret).loads(
            signed,
            max_age=_RETRY_COOKIE_MAX_AGE,
        )
    except BadData:
        return None
    if (
        type(payload) is not dict
        or set(payload) != {"public_id", "phase"}
        or type(payload.get("public_id")) is not str
        or _PUBLIC_ID_PATTERN.fullmatch(payload["public_id"]) is None
        or payload.get("phase") not in {"seed", "linked"}
    ):
        return None
    return {
        "public_id": payload["public_id"],
        "phase": payload["phase"],
    }


def _signed_retry_state(
    secret: str,
    public_id: str,
    phase: str,
) -> str:
    return _retry_serializer(secret).dumps(
        {"public_id": public_id, "phase": phase}
    )


def _record_payment_link_failure(repo, order, now: datetime) -> None:
    try:
        with repo.transaction() as tx:
            tx.insert_event_if_absent(
                order_id=order.id,
                event_type="payment_link_failed",
                external_reference="",
                payload_hash="",
                created_at=now,
            )
    except Exception:
        return


def _set_retry_cookie(response, signed_value: str) -> None:
    response.set_cookie(
        _RETRY_COOKIE,
        signed_value,
        max_age=_RETRY_COOKIE_MAX_AGE,
        httponly=True,
        secure=PUBLIC_BASE_URL.startswith("https://"),
        samesite="Lax",
        path="/ban-do-thu-dau-mot",
    )


def _checkout_in_progress_response(
    secret: str,
    public_id: str,
    *,
    phase: str = "linked",
):
    response = jsonify({"code": "checkout_in_progress"})
    response.status_code = 409
    _set_retry_cookie(
        response,
        _signed_retry_state(secret, public_id, phase),
    )
    return response


def _has_complete_payment_link(order) -> bool:
    return bool(
        order.payment_link_id
        and order.checkout_url
        and order.qr_code
    )


def _has_any_payment_link(order) -> bool:
    return bool(
        order.payment_link_id
        or order.checkout_url
        or order.qr_code
    )


def _cookie_authorized_order(public_id: str):
    if _PUBLIC_ID_PATTERN.fullmatch(public_id or "") is None:
        return None
    settings = get_digital_product_commerce_settings()
    if not _valid_cookie_secret(settings.cookie_secret):
        return None
    signed = request.cookies.get(_ORDER_COOKIE)
    if not signed:
        return None
    try:
        payload = _order_serializer(settings.cookie_secret).loads(
            signed,
            max_age=_ORDER_COOKIE_MAX_AGE,
        )
    except BadData:
        return None
    if (
        type(payload) is not dict
        or set(payload) != {"public_id"}
        or payload.get("public_id") != public_id
    ):
        return None
    return get_order(public_id, repo=_repository_factory())


def _order_not_found_response():
    response = jsonify({"code": "order_not_found"})
    response.status_code = 404
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _download_denied_response():
    response = jsonify({"code": "download_not_authorized"})
    response.status_code = 403
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _download_expired_response():
    response = jsonify({"code": "download_expired"})
    response.status_code = 410
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _download_unavailable_response():
    response = jsonify({"code": "download_temporarily_unavailable"})
    response.status_code = 503
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _valid_cookie_secret(secret: object) -> bool:
    return type(secret) is str and len(secret) >= 64


def _qr_svg_data_uri(payload: str) -> str | None:
    if type(payload) is not str or not payload or len(payload) > 4_096:
        return None
    output = BytesIO()
    image = qrcode.make(
        payload,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=8,
        border=4,
    )
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _order_label(order_code: int) -> str:
    value = order_code
    digits = ""
    while value:
        value, remainder = divmod(value, 36)
        digits = _BASE36_ALPHABET[remainder] + digits
    return "BD" + (digits or "0")


def _iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _order_cookie_path(public_id: str) -> str:
    return f"/api/digital-products/orders/{public_id}"
