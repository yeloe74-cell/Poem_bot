from __future__ import annotations

from poem_agent.storage.database import Database


def test_draft_requires_owner_approval_before_publish(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    draft_id = db.create_draft("မိုးစက်များကြားက အိပ်မက်တစ်ပုဒ်\nနှလုံးသားထဲမှာ တိတ်တဆိတ်ပွင့်လန်း")
    assert db.due_approved() == []
    assert db.approve(draft_id, 12345)
    assert [row["id"] for row in db.due_approved()] == [draft_id]
    assert db.mark_published(draft_id, 456)
    assert db.get_draft(draft_id)["status"] == "published"


def test_draft_cannot_be_approved_twice_or_rejected_after_approval(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    draft_id = db.create_draft("A sufficiently long poem text for the approval test.")
    assert db.approve(draft_id, 12345)
    assert not db.approve(draft_id, 12345)
    assert not db.reject(draft_id, 12345)


def test_rejected_drafts_never_enter_publish_queue(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    draft_id = db.create_draft("A sufficiently long poem text for rejecting safely.")
    assert db.reject(draft_id, 12345)
    assert db.due_approved() == []
