import socket
import logging
import signal


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
        Dummy Server loop

        Server that accept a new connections and establishes a
        communication with a client. After client with communucation
        finishes, servers starts to accept new connections again
        """
        # Handle SIGTERM signal para cerrar el server gracefully
        signal.signal(signal.SIGTERM, self._handle_sigterm)

        while self._running:
            try:
                client_sock = self.__accept_new_connection()
                self.__handle_client_connection(client_sock)
                self._clients.remove(client_sock)
            except OSError as e:
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
        Read message from a specific client socket and closes the socket

        If a problem arises in the communication with the client, the
        client socket will also be closed
        """
        try:
            # TODO: Modify the receive to avoid short-reads
            msg = client_sock.recv(1024).rstrip().decode('utf-8')
            addr = client_sock.getpeername()
            logging.info(f'action: receive_message | result: success | ip: {addr[0]} | msg: {msg}')
            # TODO: Modify the send to avoid short-writes
            client_sock.send("{}\n".format(msg).encode('utf-8'))
        except OSError as e:
            logging.error("action: receive_message | result: fail | error: {e}")
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
