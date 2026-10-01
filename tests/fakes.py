class FakeLLMProvider:
    """Queue of AgentDecision objects or Exceptions, returned in order."""
    def __init__(self, *items):
        self.queue = list(items)
        self.calls = []

    def classify(self, email_text: str, context: dict):
        self.calls.append((email_text, context))
        if not self.queue:
            raise RuntimeError("FakeLLMProvider queue is empty!")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
