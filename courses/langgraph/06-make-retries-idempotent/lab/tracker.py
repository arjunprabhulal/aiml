"""A stub issue tracker. It honors an idempotency key, and it can lose the response after creating a ticket."""


class Tracker:
    def __init__(self, lost_responses: int = 0):
        self.tickets: list[dict] = []
        self.keys: dict[str, dict] = {}
        self.requests: list[str | None] = []  # the key sent with each create request
        self.lost_responses = lost_responses

    def create(self, title: str, labels: list[str], idempotency_key: str | None = None) -> dict:
        self.requests.append(idempotency_key)
        if idempotency_key in self.keys:  # a repeat of a request it already handled
            return {**self.keys[idempotency_key], "replayed": True}
        ticket = {"id": f"REV-{101 + len(self.tickets)}", "title": title, "labels": labels}
        self.tickets.append(ticket)
        if idempotency_key:
            self.keys[idempotency_key] = ticket
        if self.lost_responses:  # the ticket exists, but the caller never hears back
            self.lost_responses -= 1
            raise TimeoutError("tracker did not answer within 5s")
        return ticket
