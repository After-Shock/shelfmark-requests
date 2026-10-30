"""Admin accepts or declines the series pack offered for a request with no solo release."""

from unittest.mock import MagicMock, patch

from tests.core.test_request_routes_prerelease import _make_app, _set_user_session

OFFERED = {
    "id": 398, "title": "The Dead Guy Next Door", "status": "failed", "content_type": "audiobook",
    "user_id": 7, "series_pack_offer": "Riley Thorn Series 1 -4", "canonical_request_id": None,
}


def _post(body, request=OFFERED):
    request_db = MagicMock()
    request_db.get_request.return_value = request
    request_db.update_request_status.side_effect = lambda rid, status, **k: {**request, "status": status, **k}
    app = _make_app(request_db, MagicMock())
    with app.test_client() as client:
        _set_user_session(client, is_admin=True)
        with patch("shelfmark.core.request_routes._broadcast_request_update"), \
             patch("shelfmark.core.request_routes._acquire_download_slot", return_value=True), \
             patch("shelfmark.core.request_routes.threading.Thread") as thread_cls:
            resp = client.post("/api/requests/398/series-pack", json=body)
    return resp, request_db, thread_cls


def test_accepting_grabs_the_pack():
    resp, request_db, thread_cls = _post({"accept": True})
    assert resp.status_code == 200
    request_db.update_request_status.assert_called_once_with(398, "approved", approved_by=1)
    assert thread_cls.call_args.kwargs["kwargs"] == {"allow_series_pack": True}
    thread_cls.return_value.start.assert_called_once()


def test_declining_clears_the_offer_without_downloading():
    resp, request_db, thread_cls = _post({"accept": False})
    assert resp.status_code == 200
    request_db.update_request_status.assert_called_once_with(
        398, "failed", series_pack_offer="", admin_note="Series pack 'Riley Thorn Series 1 -4' declined"
    )
    thread_cls.assert_not_called()


def test_nothing_to_accept_without_an_offer():
    resp, request_db, thread_cls = _post({"accept": True}, request={**OFFERED, "series_pack_offer": None})
    assert resp.status_code == 409
    request_db.update_request_status.assert_not_called()
    thread_cls.assert_not_called()
