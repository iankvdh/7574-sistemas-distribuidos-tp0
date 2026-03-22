import socket
import logging
import signal

from common.bet_message import BatchParseError, parse_batch_message, parse_end_message, parse_query_message, BATCH_MSG_TYPE, END_MSG_TYPE, QUERY_MSG_TYPE, WINNERS_MSG_TYPE
from common.utils import has_won, load_bets, store_bets
from protocol.protocol import read_frame, write_frame, ACK_OK, ACK_FAIL, ACK_WAIT


class Server:
    def __init__(self, port, listen_backlog):
        # Initialize server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.bind(('', port))
        self._server_socket.listen(listen_backlog)
        self._running = True
        self._clients = []
        self._finished_agencies = set()
        self._bets_over = False
        self._winners_by_agency = {}

    def _handle_sigterm(self, signum, frame):
        logging.info("action: shutdown | result: in_progress | signal: SIGTERM")
        self._running = False
        self._server_socket.close()

    def run(self):
        """
        Main server loop

        Accepts client connections sequentially. For each connection,
        reads one framed batch message, stores it, sends an ACK/NACK, and then
        continues waiting for the next client.
        """
        # Handle SIGTERM signal para cerrar el server gracefully
        signal.signal(signal.SIGTERM, self._handle_sigterm)

        while self._running:
            try:
                client_sock = self.__accept_new_connection()
                self.__handle_client_connection(client_sock)
                self._clients.remove(client_sock)
            except OSError as e:
                if self._running:
                    logging.error(f"action: accept_connections | result: fail | error: {e}")
                break

        for client in self._clients:
            try:
                client.close()
                logging.info(
                    f"action: shutdown | result: success | closed_client_ip: {client.getpeername()[0]}"
                )
            except Exception:
                logging.error(
                    f"action: shutdown | result: fail | error: Could not close client socket (unknown IP)"
                )
        logging.info("action: shutdown | result: success | closed: server_socket")

    def __handle_client_connection(self, client_sock):
        """
        Handles one client connection.

        Receives a single framed message and processes it according to its type:

        - "BATCH": parses and stores a batch of bets, responds with ACK/NACK.
        - "END": marks an agency as finished; when all agencies are done,
        triggers the draw and computes winners.
        - "QUERY": returns winners for a given agency if the draw is complete,
        otherwise responds with WAIT.
        """
        addr = ("unknown", 0)
        batch_count = 0
        try:
            addr = client_sock.getpeername()

            msg = read_frame(client_sock).decode('utf-8')
            logging.info(f'action: receive_message | result: success | ip: {addr[0]}')

            if msg.startswith(BATCH_MSG_TYPE+"\n"):
                bets = parse_batch_message(msg)
                batch_count = len(bets)
                store_bets(bets)
                logging.info(
                    f"action: apuesta_recibida | result: success | cantidad: {batch_count}"
                )
                write_frame(client_sock, ACK_OK)
                return

            if msg.startswith(END_MSG_TYPE+"|"):
                agency = parse_end_message(msg)
                self._finished_agencies.add(agency)
                if len(self._finished_agencies) == 5 and not self._bets_over:
                    self.__run_winners_by_agency()
                    logging.info("action: sorteo | result: success")
                write_frame(client_sock, ACK_OK)
                return

            if msg.startswith(QUERY_MSG_TYPE+"|"):
                agency = parse_query_message(msg)
                if not self._bets_over:
                    write_frame(client_sock, ACK_WAIT)
                    return

                winners = self._winners_by_agency.get(agency, [])
                winners_payload = "{}|{}|{}".format(
                    WINNERS_MSG_TYPE,
                    len(winners),
                    ",".join(winners),
                )
                write_frame(client_sock, winners_payload.encode("utf-8"))
                return

            raise ValueError("unsupported message payload")
        except OSError as e:
            logging.error(f"action: receive_message | result: fail | error: {e}")
        except BatchParseError as e:
            batch_count = e.count
            logging.info(
                f"action: apuesta_recibida | result: fail | cantidad: {batch_count}"
            )
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass
        except ValueError:
            logging.info(
                f"action: apuesta_recibida | result: fail | cantidad: {batch_count}"
            )
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass
        finally:
            client_sock.close()

    def __accept_new_connection(self):
        """
        Accept new connections

        Function blocks until a connection to a client is made.
        Then connection created is printed and returned
        """

        # Connection arrived
        logging.info('action: accept_connections | result: in_progress')
        c, addr = self._server_socket.accept()
        logging.info(f'action: accept_connections | result: success | ip: {addr[0]}')
        self._clients.append(c)
        return c

    def __run_winners_by_agency(self):
        """
        Computes winners grouped by agency.

        Marks the betting phase as finished, loads all stored bets,
        evaluates which bets have won, and builds an in-memory mapping:

            agency -> list of winner document IDs
        """

        self._bets_over = True
        bets = list(load_bets())
        for bet in bets:
            if has_won(bet):
                agency = str(bet.agency)
                if agency not in self._winners_by_agency:
                    self._winners_by_agency[agency] = []
                self._winners_by_agency[agency].append(str(bet.document))
