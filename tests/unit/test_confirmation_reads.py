from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.connectors.confirmation import matches_confirmation
from app.connectors.http import ReadOnlyHTTP
from app.connectors.servicedesk import ServiceDesk
from app.contracts.context import ApprovalReviewRequest


def review(**changes):
    fields = dict(ticket_id="1", approval_ref="original-review", cycle_id="c" * 64,
                  terms_digest="a" * 64, configuration_digest="b" * 64,
                  original_approver_ids=("90", "91"))
    fields.update(changes)
    return ApprovalReviewRequest(**fields)


@pytest.mark.parametrize("field,value", [
    ("ticket_id", "2"), ("approval_ref", "another-review"), ("cycle_id", "d" * 64),
    ("terms_digest", "d" * 64), ("configuration_digest", "d" * 64),
    ("original_approver_ids", ("90",)),
])
def test_review_reference_binds_ticket_cycle_terms_config_and_original_reviewers(field, value):
    assert review().review_ref() != review(**{field: value}).review_ref()
    assert review().review_ref() == review(original_approver_ids=("91", "90")).review_ref()
    with pytest.raises(ValidationError):
        review(original_approver_ids=("90", "90"))


@pytest.mark.parametrize("wrapper", ["{}", "  {}\n", "<div>{}</div>",
                                     '<p dir="ltr"><strong>{}</strong></p>', "<div>{}<br></div>"])
def test_plain_and_basic_html_confirmation_format(wrapper):
    request = review()
    assert matches_confirmation(wrapper.format(request.confirmation_text()), request)


@pytest.mark.parametrize("body", [
    "Not approved: {}", "Quoted approval: {}", "{} but only half the budget",
    '<div style="display:none">{}</div>', '<span onclick="send()">{}</span>',
    "<script>{}</script>", "<div>{}", "<!--{}-->", "<div>{}</p>",
    "Approved Mirza terms: another-review", "Approved Mirza terms: {}",
    "{}" + " " * 9000, None, "\ud800",
])
def test_denials_extra_terms_hidden_or_malformed_content_does_not_match(body):
    request = review()
    if body is not None:
        body = body.format(request.confirmation_text())
    assert not matches_confirmation(body, request)


@pytest.mark.parametrize("case", [
    "match", "unrelated_author", "edited_by_other", "unknown_editor", "changed_body",
    "changed_author", "wrong_request", "unknown_author", "unrelated_review", "denied",
])
async def test_confirmation_reader_binds_visible_terms_without_inventing_history_or_grants(case):
    counts = {"list": 0, "detail": 0}
    calls = []
    request = review()

    def handle(http_request):
        calls.append(http_request)
        if http_request.url.path.endswith("/notes"):
            counts["list"] += 1
            return httpx.Response(200, json={
                "response_status": {"status": "success", "status_code": 2000},
                "notes": [{"id": "10"}], "list_info": {"has_more_rows": False},
            })
        counts["detail"] += 1
        if case == "denied" and counts["detail"] == 2:
            return httpx.Response(403, text="sk-secret employee@example.invalid")
        body = request.confirmation_text()
        author = "90"
        if case == "unrelated_review":
            body = review(cycle_id="d" * 64).confirmation_text()
        if case == "changed_body" and counts["detail"] == 2:
            body += " sk-secret employee@example.invalid"
        if case == "unrelated_author" or (case == "changed_author" and counts["detail"] == 2):
            author = "92"
        return httpx.Response(200, json={
            "response_status": {"status": "success", "status_code": 2000},
            "note": {
                "id": "10", "request": {"id": "2" if case == "wrong_request" else "1"},
                "description": f"<div>{body}</div>",
                "added_by": None if case == "unknown_author" else {"id": author},
                "added_time": {"value": 1000},
                "last_updated_by": {"id": "92"} if case == "edited_by_other" else None,
                "last_updated_time": {"value": 2000}
                    if case in {"edited_by_other", "unknown_editor"} else None,
            },
        })

    http = ReadOnlyHTTP("https://fixture.invalid", SecretStr("private-technician-token"),
                        ServiceDesk.PATHS, transport=httpx.MockTransport(handle), sleep=AsyncMock())
    try:
        result = await ServiceDesk(http).confirmation_notes("1", request)
        if case in {"changed_body", "changed_author"}:
            assert result.status == "unstable" and result.data is None
        elif case == "denied":
            assert result.status == "unavailable" and result.data is None
        elif case == "wrong_request":
            assert result.status == "invalid" and result.data is None
        elif case == "unknown_author":
            assert result.status == "incomplete" and result.data is None
        elif case == "unrelated_review":
            assert result.status == "ok" and result.data == ()
        else:
            assert result.status == "ok" and len(result.data) == 1
            note = result.data[0]
            assert note.terms_digest == request.terms_digest and note.terms_verified
            assert note.author_verified is (case == "match")
            assert note.source_sequence is None and not note.history_verified
        serialized = result.model_dump_json()
        assert "sk-secret" not in serialized and "employee@" not in serialized
        assert request.confirmation_text() not in serialized
        assert all(call.method == "GET" and call.url.host == "fixture.invalid" for call in calls)
    finally:
        await http.close()


async def test_cross_ticket_review_is_rejected_before_any_read():
    desk = ServiceDesk(AsyncMock())
    result = await desk.confirmation_notes("2", review())
    assert result.status == "invalid"
    desk.http.get.assert_not_awaited()
