"""Approved requests must fall through to the next release when a download fails."""
import sys
import types

from shelfmark.core import request_routes as rr


class FakeRequestDB:
    def __init__(self):
        self.status = None
        self.task_id = None

    def get_request(self, request_id):
        return {"id": request_id}

    def update_request_status(self, request_id, status, **kwargs):
        self.status = status
        if "download_task_id" in kwargs:
            self.task_id = kwargs["download_task_id"]
        return {"id": request_id, "status": status}


def _install_fake_orchestrator(results):
    """queue_release returns results.pop(0) each call; records the md5s tried."""
    tried = []
    mod = types.ModuleType("shelfmark.download.orchestrator")

    def queue_release(release_data, **kwargs):
        tried.append(release_data["source_id"])
        return results.pop(0), "boom"

    mod.queue_release = queue_release
    sys.modules["shelfmark.download.orchestrator"] = mod
    return tried


def _seed(request_id, md5s):
    with rr._retry_lock:
        rr._release_retries[request_id] = {
            "candidates": [{"source_id": m} for m in md5s],
            "user_overrides": {},
            "admin_user_id": 1,
            "admin_username": "admin",
            "user_db": None,
            "attempted": 0,
        }


def main():
    rr._broadcast_request_update = lambda *a, **k: None
    rr._send_group_status_notifications = lambda *a, **k: None
    db = FakeRequestDB()

    # Each failure advances to the next candidate, then gives up after the third.
    tried = _install_fake_orchestrator([True, True, True])
    _seed(1, ["aaa", "bbb", "ccc"])
    assert rr._queue_next_release(db, 1) is True
    assert db.task_id == "aaa"
    assert rr.retry_next_release(db, 1) is True
    assert db.task_id == "bbb"
    assert rr.retry_next_release(db, 1) is True
    assert db.task_id == "ccc"
    assert rr.retry_next_release(db, 1) is False, "must give up after the cap"
    assert tried == ["aaa", "bbb", "ccc"], tried
    assert 1 not in rr._release_retries, "state must not leak"

    # A release that won't even queue is skipped rather than stalling the request.
    tried = _install_fake_orchestrator([False, True])
    _seed(2, ["xxx", "yyy"])
    assert rr._queue_next_release(db, 2) is True
    assert tried == ["xxx", "yyy"], tried
    assert db.task_id == "yyy"

    # Fulfilled requests drop their spares.
    _seed(3, ["zzz"])
    rr.forget_release_retries(3)
    assert 3 not in rr._release_retries

    print("ok")


if __name__ == "__main__":
    main()
