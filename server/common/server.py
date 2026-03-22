import socket
import logging
import signal
from threading import Lock, Thread

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
        self._client_threads = []
        self._clients_lock = Lock()      # protege altas/bajas de sockets y lista de threads.
        self._state_lock = Lock()        # protege estructuras compartidas: finished_agencies, winners_by_agency.
        self._storage_lock = Lock()      # serializa escritura/lectura de STORAGE_FILEPATH.
        self._finished_agencies = set()
        self._winners_by_agency = {}

    def _handle_sigterm(self, signum, frame):
        logging.info("action: shutdown | result: in_progress | signal: SIGTERM")
        self._running = False
        self._server_socket.close()

    def run(self):
        """
        Main server loop

        Accepts client connections and dispatches one worker thread per
        connection, allowing concurrent request handling.
        """
        # Handle SIGTERM signal para cerrar el server gracefully
        signal.signal(signal.SIGTERM, self._handle_sigterm)

        while self._running:
            try:
                client_sock = self.__accept_new_connection()
                client_thread = Thread(
                    target=self.__handle_client_connection,
                    args=(client_sock,),
                    daemon=True, # si el servidor principal muere, los hilos se cierran automáticamente.
                )
                with self._clients_lock:
                    self._client_threads.append(client_thread)
                client_thread.start()
            except OSError as e:
                if self._running:
                    logging.error(f"action: accept_connections | result: fail | error: {e}")
                break

        with self._clients_lock:
            clients = list(self._clients)
            threads = list(self._client_threads)

        for client in clients:
            try:
                client.close()
                logging.info(
                    f"action: shutdown | result: success | closed_client_ip: {client.getpeername()[0]}"
                )
            except Exception:
                logging.error(
                    f"action: shutdown | result: fail | error: Could not close client socket (unknown IP)"
                )

        for thread in threads:
            thread.join(timeout=1)

        logging.info("action: shutdown | result: success | closed: server_socket")

    def __handle_client_connection(self, client_sock):
        """
        Handles one client connection.

        Receives a single framed message and processes it according to its type:

        - "BATCH": parses and stores a batch of bets, responds with ACK/NACK.
        - "END": marks an agency as finished and refreshes winners snapshot.
        - "QUERY": returns winners for a given agency if that agency already
                    sent END; otherwise responds with WAIT.
        """
        addr = ("unknown", 0)
        batch_count = 0
        message_type = "unknown"
        try:
            addr = client_sock.getpeername()

            msg = read_frame(client_sock).decode('utf-8')
            logging.info(f'action: receive_message | result: success | ip: {addr[0]}')

            if msg.startswith(BATCH_MSG_TYPE+"\n"):
                message_type = "batch"
                bets = parse_batch_message(msg)
                batch_count = len(bets)
                with self._storage_lock:
                    store_bets(bets)
                logging.info(
                    f"action: apuesta_recibida | result: success | cantidad: {batch_count}"
                )
                write_frame(client_sock, ACK_OK)
                return

            if msg.startswith(END_MSG_TYPE+"|"):
                message_type = "end"
                agency = parse_end_message(msg)
                with self._state_lock:
                    self._finished_agencies.add(agency)
                self.__run_winners_by_agency()
                logging.info("action: sorteo | result: success")
                write_frame(client_sock, ACK_OK)
                return

            if msg.startswith(QUERY_MSG_TYPE+"|"):
                message_type = "query"
                agency = parse_query_message(msg)
                with self._state_lock:
                    agency_finished = agency in self._finished_agencies
                    winners = list(self._winners_by_agency.get(agency, []))

                if not agency_finished:
                    write_frame(client_sock, ACK_WAIT)
                    return

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
            if message_type == "batch":
                logging.info(
                    f"action: apuesta_recibida | result: fail | cantidad: {batch_count}"
                )
            elif message_type == "end":
                logging.info("action: fin_envio | result: fail")
            elif message_type == "query":
                logging.info("action: consulta_ganadores | result: fail")
            else:
                logging.info("action: process_message | result: fail")
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass
        finally:
            self.__remove_client(client_sock)
            client_sock.close()

    def __accept_new_connection(self):
        """
        Accepts one incoming TCP connection and tracks it as active.
        """

        logging.info('action: accept_connections | result: in_progress')
        c, addr = self._server_socket.accept()
        logging.info(f'action: accept_connections | result: success | ip: {addr[0]}')
        with self._clients_lock:
            self._clients.append(c)
        return c

    def __remove_client(self, client_sock):
        with self._clients_lock:
            if client_sock in self._clients:
                self._clients.remove(client_sock)

    def __run_winners_by_agency(self):
        """
        Recomputes winners grouped by agency from persisted bets.

        Loads all stored bets, evaluates winners, and replaces the in-memory
        winners snapshot with:

            agency -> list of winner document IDs
        """

        with self._storage_lock:
            bets = list(load_bets())

        winners_by_agency = {}
        for bet in bets:
            if has_won(bet):
                agency = str(bet.agency)
                if agency not in winners_by_agency:
                    winners_by_agency[agency] = []
                winners_by_agency[agency].append(str(bet.document))

        with self._state_lock:
            self._winners_by_agency = winners_by_agency
