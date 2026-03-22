from common.utils import Bet

BET_MSG_TYPE = "BET"


# parse_bet_message parsea un mensaje de apuesta con formato:
# BET|agency|nombre|apellido|documento|nacimiento|numero
# Valida el formato y devuelve un objeto Bet.
def parse_bet_message(message):
    parts = message.split("|")
    if len(parts) != 7:
        raise ValueError("invalid bet format")

    msg_type, agency, first_name, last_name, document, birthdate, number = parts
    if msg_type != BET_MSG_TYPE:
        raise ValueError("unsupported message type")

    return Bet(agency, first_name, last_name, document, birthdate, number)
