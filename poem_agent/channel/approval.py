"""Draft approval state transitions."""

from poem_agent.storage.database import Database


class ApprovalService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def approve(self, draft_id: str, owner_id: int) -> bool:
        return self.database.approve(draft_id, owner_id)

    def reject(self, draft_id: str, owner_id: int) -> bool:
        return self.database.reject(draft_id, owner_id)
