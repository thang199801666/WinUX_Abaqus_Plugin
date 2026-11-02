"""Incremental terminal delivery, including bounded scrollback rollover."""


class TerminalStreamReader:
    def __init__(self):
        self.generation = None
        self.cursor = None
        self.previous = ""

    def read(self, payload):
        """Return (new text, needs reset). Legacy string callbacks still work."""
        if isinstance(payload, dict):
            text = str(payload.get("text") or "")
            generation = payload.get("generation")
            end = int(payload["end"])
            start = end - len(text)
            reset = (self.cursor is not None and
                     (generation != self.generation or self.cursor < start or self.cursor > end))
            offset = 0 if reset or self.cursor is None else self.cursor - start
            delta = text[offset:]
            self.generation, self.cursor, self.previous = generation, end, ""
            return delta, reset
        text = str(payload or "")
        reset = bool(self.cursor is not None or self.previous and not text.startswith(self.previous))
        delta = text if reset else text[len(self.previous):]
        self.previous = text
        self.generation = self.cursor = None
        return delta, reset
