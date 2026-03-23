import os
import socket
import logging
import signal
import hashlib
from multiprocessing import Lock, Manager, Process, Semaphore

from common.bet_message import BatchParseError, parse_batch_message, parse_end_message, parse_query_message, BATCH_MSG_TYPE, END_MSG_TYPE, QUERY_MSG_TYPE, WINNERS_MSG_TYPE
from common.utils import has_won, store_bets
from protocol.protocol import read_frame, write_frame, ACK_OK, ACK_FAIL, ACK_WAIT

WINNERS_DIRPATH = "./winners"


class Server:
    def __init__(self, port, listen_backlog, max_workers=None):
        # Initialize server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.bind(('', port))
        self._server_socket.listen(listen_backlog)
        self._running = True
        self._max_workers = max_workers if max_workers is not None else listen_backlog
        if self._max_workers <= 0:
            raise ValueError("max_workers must be > 0")
        self._worker_slots = Semaphore(self._max_workers)   # Limita la cantidad de procesos que pueden trabajar al mismo tiempo. Las conexiones extra quedan esperando en el TCP backlog.
        self._worker_processes = []  # Almacena las referencias a procesos hijos activos.
        self._worker_processes_lock = Lock()   # Sincroniza el acceso a la lista de procesos.
        self._finished_agencies_lock = Lock()  # incroniza el acceso a la lista de agencias finalizadas.
        self._bets_file_lock = Lock()  # Acceso exclusivo de escritura para STORAGE_FILEPATH.
        self._winners_file_locks = [Lock() for _ in range(16)] # Locks segmentados para reducir contencion entre agencias distintas.
        self._manager = Manager()        # para compartir objetos entre procesos separados.
        self._finished_agencies = self._manager.dict() # Diccionario compartido

        self.__initialize_winners_storage()

    def _handle_sigterm(self, signum, frame):
        logging.info("action: shutdown | result: in_progress | signal: SIGTERM")
        self._running = False
        self._server_socket.close()

    def run(self):
        """
        Main server loop.

        Accepts client connections and dispatches one worker process per
        connection, allowing concurrent request handling.
        """
        # Handle SIGTERM signal para cerrar el server gracefully
        signal.signal(signal.SIGTERM, self._handle_sigterm)

        while self._running:
            try:
                worker_started = False
                self._worker_slots.acquire() # Se bloquea cuando se alcanza el máximo de procesos activos.
                client_sock = self.__accept_new_connection()
                worker = Process( # Crea un proceso hijo independiente para manejar al cliente.
                    target=self.__handle_client_connection,
                    args=(client_sock,),
                    daemon=True, # El hijo muere si el padre muere.
                )
                with self._worker_processes_lock:
                    self._worker_processes.append(worker)
                worker.start()
                worker_started = True

                client_sock.close() # El padre cierra su copia del socket; solo el hijo lo usa.
                self.__reap_finished_workers()
            except OSError as e:
                if not worker_started:
                    self._worker_slots.release()
                if self._running:
                    logging.error(f"action: accept_connections | result: fail | error: {e}")
                break
            except Exception:
                if not worker_started:
                    self._worker_slots.release()
                raise

        with self._worker_processes_lock: # Al salir del loop, espera a que los procesos hijos terminen.
            workers = list(self._worker_processes)

        for worker in workers:
            worker.join(timeout=1)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=1)

        self._manager.shutdown() # Cierra el servidor de objetos compartidos.
        logging.info("action: shutdown | result: success | closed: server_socket")

    def __handle_client_connection(self, client_sock):
        """
        Handles one client connection.

        Receives a single framed message and processes it according to its type:

                - "BATCH": parses and stores a batch of bets, responds with ACK/NACK.
                - "END": marks an agency as finished.
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

                winners_by_agency = self.__extract_winners_by_agency(bets)
                with self._bets_file_lock:
                    store_bets(bets)
                self.__append_winners_by_agency(winners_by_agency)
                logging.info(
                    f"action: apuesta_recibida | result: success | cantidad: {batch_count}"
                )
                write_frame(client_sock, ACK_OK)
                return

            if msg.startswith(END_MSG_TYPE+"|"):
                message_type = "end"
                agency = parse_end_message(msg)
                with self._finished_agencies_lock:
                    self._finished_agencies[agency] = True
                logging.info("action: sorteo | result: success")
                write_frame(client_sock, ACK_OK)
                return

            if msg.startswith(QUERY_MSG_TYPE+"|"):
                message_type = "query"
                agency = parse_query_message(msg)
                with self._finished_agencies_lock:
                    agency_finished = bool(self._finished_agencies.get(agency, False))

                if not agency_finished:
                    write_frame(client_sock, ACK_WAIT)
                    return

                winners = self.__load_winners_for_agency(agency)

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
        except Exception as e:
            logging.error(f"action: process_message | result: fail | error: {e}")
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass
        finally:
            self._worker_slots.release()
            client_sock.close()

    def __accept_new_connection(self):
        """
        Accepts one incoming TCP connection and tracks it as active.
        """

        logging.info('action: accept_connections | result: in_progress')
        c, addr = self._server_socket.accept()
        logging.info(f'action: accept_connections | result: success | ip: {addr[0]}')
        return c

    def __initialize_winners_storage(self):
        """
        Initializes winners storage directory for current server execution.
        """
        os.makedirs(WINNERS_DIRPATH, exist_ok=True)
        for filename in os.listdir(WINNERS_DIRPATH):
            filepath = os.path.join(WINNERS_DIRPATH, filename)
            if os.path.isfile(filepath):
                os.remove(filepath)

    def __winner_file_path(self, agency):
        return os.path.join(WINNERS_DIRPATH, f"agency-{agency}.winners")

    def __winner_lock_for_agency(self, agency):
        """
        Returns a deterministic winners-file lock for a given agency.

        Uses lock striping to keep synchronization simple while reducing
        unnecessary blocking between different agencies.
        """

        #  Hash (DETERMINISTICO) de la agencia para asignarle un lock específico entre los disponibles.
        agency_key = str(agency).encode("utf-8")
        digest = hashlib.blake2b(agency_key, digest_size=8).digest()
        idx = int.from_bytes(digest, byteorder="big") % len(self._winners_file_locks)
        

        return self._winners_file_locks[idx]

    def __reap_finished_workers(self):
        """
        Removes finished worker processes from the tracking list.
        """

        with self._worker_processes_lock:
            alive_workers = []
            for worker in self._worker_processes:
                if worker.is_alive():
                    alive_workers.append(worker)
                else:
                    worker.join(timeout=0)
            self._worker_processes = alive_workers

    def __extract_winners_by_agency(self, bets):
        """
        Builds an in-memory mapping agency -> winner documents for one batch.
        """

        winners_by_agency = {}
        for bet in bets:
            if has_won(bet):
                agency = str(bet.agency)
                if agency not in winners_by_agency:
                    winners_by_agency[agency] = []
                winners_by_agency[agency].append(str(bet.document))

        return winners_by_agency

    def __append_winners_by_agency(self, winners_by_agency):
        """
        Appends winner documents grouped by agency to winners files.
        """

        for agency, documents in winners_by_agency.items():
            filepath = self.__winner_file_path(agency)
            with self.__winner_lock_for_agency(agency):
                with open(filepath, "a", encoding="utf-8") as file:
                    for document in documents:
                        file.write(f"{document}\n")

    def __load_winners_for_agency(self, agency):
        filepath = self.__winner_file_path(agency)
        with self.__winner_lock_for_agency(agency):
            if not os.path.exists(filepath):
                return []

            with open(filepath, "r", encoding="utf-8") as file:
                return [line.strip() for line in file if line.strip()]
