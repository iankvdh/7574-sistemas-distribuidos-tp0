from common.utils import Bet

BATCH_MSG_TYPE = "BATCH"


class BatchParseError(ValueError):
    def __init__(self, message, count):
        super().__init__(message)
        self.count = count


def _parse_bet_row(row):
    parts = row.split("|")
    if len(parts) != 6:
        raise ValueError("invalid bet row format")

    agency, first_name, last_name, document, birthdate, number = parts
    return Bet(agency, first_name, last_name, document, birthdate, number)


# parse_batch_message arsea un payload batch con el formato:
# BATCH\n
# agency|first_name|last_name|document|birthdate|number\n
def parse_batch_message(message):
    lines = [line for line in message.splitlines() if line.strip() != ""]
    if len(lines) < 2:
        raise BatchParseError("empty batch", 0)

    if lines[0] != BATCH_MSG_TYPE:
        raise BatchParseError("unsupported message type", max(0, len(lines)-1))

    rows = lines[1:]
    count = len(rows)
    bets = []
    try:
        for row in rows:
            bets.append(_parse_bet_row(row))
    except ValueError as exc:
        raise BatchParseError(str(exc), count)

    return bets
