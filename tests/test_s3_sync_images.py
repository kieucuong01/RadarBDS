import pytest

from scripts import s3_sync_images


def test_prune_cli_defaults_to_dry_run():
    args = s3_sync_images.parse_args(["--prune-local"])

    assert args.prune_local is True
    assert args.apply is False


def test_apply_is_rejected_for_nonprune_modes():
    with pytest.raises(SystemExit) as exc_info:
        s3_sync_images.parse_args(["--verify", "--apply"])

    assert exc_info.value.code == 2


def test_prune_apply_rejects_noncanonical_root(tmp_path, monkeypatch):
    other = tmp_path / "data" / "images"
    other.mkdir(parents=True)
    called = []
    monkeypatch.setattr(
        s3_sync_images,
        "prune_verified_local_images",
        lambda *_args, **_kwargs: called.append(True),
    )

    status = s3_sync_images.main(["--prune-local", "--apply", "--root", str(other)])

    assert status == 2
    assert called == []


def test_prune_cli_forwards_apply_and_returns_failure_status(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        s3_sync_images,
        "prune_verified_local_images",
        lambda root, *, apply: captured.update(root=root, apply=apply) or {
            "local_files": 1,
            "local_bytes": 10,
            "eligible_files": 1,
            "eligible_bytes": 10,
            "missing_remote_files": 0,
            "missing_remote_bytes": 0,
            "deleted_files": 0,
            "deleted_bytes": 0,
            "delete_failures": 1,
        },
    )

    status = s3_sync_images.main(["--prune-local", "--apply"])

    assert status == 1
    assert captured == {
        "root": (s3_sync_images.PROJECT_ROOT / "data" / "images").resolve(),
        "apply": True,
    }
