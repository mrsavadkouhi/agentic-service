"""Match the agreed note syntax privately; matching terms does not prove approval order."""

from html.parser import HTMLParser

from app.contracts.context import ApprovalReviewRequest

MAX_CONFIRMATION_BYTES = 8192


class ConfirmationText(HTMLParser):
    # ServiceDesk's editor wraps notes in basic HTML. Reject active, hidden or
    # attributed markup; keep visible text and paragraph boundaries only.
    tags = {"div", "p", "span", "b", "strong", "i", "em", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.stack = [], []
        self.valid = True

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags or any(
            key != "dir" or value not in {"ltr", "rtl", "auto"} for key, value in attrs
        ):
            self.valid = False
        if tag in {"div", "p", "br"}:
            self.parts.append("\n")
        if tag != "br":
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1] != tag:
            self.valid = False
        else:
            self.stack.pop()
        if tag in {"div", "p"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_decl(self, decl):
        self.valid = False

    def unknown_decl(self, data):
        self.valid = False

    def handle_pi(self, data):
        self.valid = False


def matches_confirmation(description: str, review: ApprovalReviewRequest) -> bool:
    if not isinstance(description, str):
        return False
    try:
        if len(description.encode()) > MAX_CONFIRMATION_BYTES:
            return False
        parser = ConfirmationText()
        parser.feed(description)
        parser.close()
        return (
            parser.valid and not parser.stack
            and "".join(parser.parts).strip() == review.confirmation_text()
        )
    except Exception:
        return False
