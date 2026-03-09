from __future__ import annotations

import logging
import queue

class TkTextHandler(logging.Handler):
    def __init__(self, msg_queue: "queue.Queue[str]") -> None:
        super().__init__()
        self.msg_queue = msg_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.msg_queue.put(self.format(record))
        except Exception:
            pass
