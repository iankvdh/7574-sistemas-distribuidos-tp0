import socket
import logging
import signal

from common.bet_message import parse_bet_message
from common.utils import store_bets
from protocol.protocol import read_frame, write_frame, ACK_OK


class Server:
    def __init__(self, port, listen_backlog):
        # Initialize server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.bind(('', port))
        self._server_socket.listen(listen_backlog)
        self._running = True
        self._clients = []

    def _handle_sigterm(self, signum, frame):
        logging.info("action: shutdown | result: in_progress | signal: SIGTERM")
        self._running = False
        self._server_socket.close()

    def run(self):
        """
        Main server loop

        Accepts client connections sequentially. For each connection,
        reads one framed bet message, stores it, sends an ACK, and then
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

        Receives one framed message, parses and stores the bet,
        responds with ACK, and always closes the socket.
        """
        addr = ("unknown", 0)
        try:
            addr = client_sock.getpeername()

            msg = read_frame(client_sock).decode('utf-8')
            logging.info(f'action: receive_message | result: success | ip: {addr[0]} | msg: {msg}')

            bet = parse_bet_message(msg)
            store_bets([bet])
            logging.info(
                f"action: apuesta_almacenada | result: success | dni: {bet.document} | numero: {bet.number}"
            )

            write_frame(client_sock, ACK_OK)
        except OSError as e:
            logging.error(f"action: receive_message | result: fail | error: {e}")
        except ValueError as e:
            logging.error(f"action: receive_message | result: fail | ip: {addr[0]} | error: {e}")
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
