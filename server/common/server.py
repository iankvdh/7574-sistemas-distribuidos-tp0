import socket
import logging
import signal
import multiprocessing
import os

from common.bet_message import BatchParseError, parse_batch_message, parse_end_message, parse_query_message, BATCH_MSG_TYPE, END_MSG_TYPE, QUERY_MSG_TYPE, WINNERS_MSG_TYPE
from common.utils import has_won, load_bets, store_bets, STORAGE_FILEPATH
from protocol.protocol import read_frame, write_frame, ACK_OK, ACK_FAIL


class Server:
    def __init__(self, port, listen_backlog, agencies_expected):
        # borramos el archivo de apuestas al iniciar el servidor para empezar limpio cada vez
        if os.path.exists(STORAGE_FILEPATH):
            os.remove(STORAGE_FILEPATH)
        
        # Initialize server socket
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.bind(('', port))
        self._server_socket.listen(listen_backlog)
        self._running = True
        self._agencies_expected = agencies_expected
        self._child_processes = []
        self._client_sockets = []  # Referencias a sockets de clientes para cerrarlos en shutdown
        
        # Estado compartido usando multiprocessing.Manager()
        self._manager = multiprocessing.Manager()
        self._winners_by_agency = self._manager.dict()  # agencia -> [dni...]
        self._bets_lock = self._manager.Lock()  # Lock para store_bets()

        # Barrera que sincroniza los N procesos hijos. Cuando todos llegaron (END recibido),
        # ejecuta el sorteo exactamente una vez (action) y recién ahí los libera a todos.
        self._barrier = multiprocessing.Barrier(agencies_expected, action=self.__run_winners_by_agency)

    def _handle_sigterm(self, signum, frame):
        """
        Handler de SIGTERM: marca running=False y cierra el socket del servidor
        para desbloquear el accept() en el main loop.
        """
        logging.info("action: shutdown | result: in_progress | signal: SIGTERM")
        self._running = False
        # Cerrar el socket del servidor para desbloquear accept()
        try:
            self._server_socket.close()
        except OSError:
            pass

    def run(self):
        """
        Main server loop with multiprocessing support.

        Accepts client connections and spawns a new process for each client.
        Each child process handles the persistent client connection.
        
        El loop principal NO usa timeout. El socket se cierra desde _handle_sigterm
        para desbloquear el accept() cuando llega SIGTERM.
        """
        # Handle SIGTERM signal
        signal.signal(signal.SIGTERM, self._handle_sigterm)

        while self._running:
            try:
                # Cada 5 conexiones nuevas, realizamos una limpieza de la lista de procesos
                if len(self._child_processes) % 5 == 0:
                    procesos_activos = []
                    for p in self._child_processes:
                        if p.is_alive():
                            procesos_activos.append(p)
                    self._child_processes = procesos_activos
                

                client_sock, addr = self._server_socket.accept()
                logging.info(f'action: accept_connections | result: success | ip: {addr[0]}')
                
                # Guardamos referencia al socket para poder cerrarlo en shutdown
                self._client_sockets.append(client_sock)
                
                # Levantamos un proceso nuevo para manejar al cliente
                process = multiprocessing.Process(
                    target=self.__handle_client_connection,
                    args=(client_sock, addr[0])
                )
                process.start()
                self._child_processes.append(process)
                
            except OSError as e:
                # Socket cerrado por shutdown o error
                if self._running:
                    logging.error(f"action: accept_connections | result: fail | error: {e}")
                break

        # Graceful shutdown
        self.__shutdown(timeout=10)

    def __handle_client_connection(self, client_sock, client_ip):
        """
        Handles a persistent client connection (runs in child process).

        The client maintains a single connection for multiple messages:
        BATCH -> END -> QUERY. This handler reads messages in a loop
        until the client disconnects or an error occurs.
        """
        # El proceso hijo ignora SIGTERM, así el shutdown lo maneja solo el proceso padre
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        
        try:
            while True:
                try:
                    frame = read_frame(client_sock)
                    if not frame:  # El cliente se fue bien
                        break
                    
                    msg = frame.decode('utf-8')
                    logging.info(f'action: receive_message | result: success | ip: {client_ip}')

                    if msg.startswith(BATCH_MSG_TYPE + "\n"):
                        self.__handle_batch(client_sock, msg, client_ip)
                    elif msg.startswith(END_MSG_TYPE + "|"):
                        self.__handle_end(client_sock, msg)
                    elif msg.startswith(QUERY_MSG_TYPE + "|"):
                        self.__handle_query(client_sock, msg)
                    else:
                        raise ValueError("unsupported message payload")
                        
                except socket.timeout:
                    # Timeout del socket → cortamos la conexión
                    break
                except OSError:
                    # Socket cerrado o error de I/O → salimos
                    break
                    
        except Exception as e:
            logging.error(f"action: client_connection | result: fail | ip: {client_ip} | error: {e}")
        finally:
            try:
                client_sock.close()
            except OSError:
                pass

    def __handle_batch(self, client_sock, msg, client_ip):
        """
        Handle BATCH message: parse, store bets with lock, send ACK.
        """
        batch_count = 0
        try:
            bets = parse_batch_message(msg)
            batch_count = len(bets)
            
            # Agarramos el lock antes de guardar
            self._bets_lock.acquire()
            try:
                store_bets(bets)
            finally:
                self._bets_lock.release()
            
            logging.info(f"action: apuesta_recibida | result: success | cantidad: {batch_count}")
            write_frame(client_sock, ACK_OK)

        except BatchParseError as e:
            batch_count = e.count
            logging.info(
                f"action: apuesta_recibida | result: fail | cantidad: {batch_count}"
            )
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass
        except Exception as e:
            logging.info(
                f"action: apuesta_recibida | result: fail | cantidad: {batch_count} | error: {e}"
            )
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass

    def __handle_end(self, client_sock, msg):
        """
        Handle END message: wait at barrier until all agencies are done, then ACK.

        barrier.wait() blocks until all N agencies call it. The last one triggers
        the action (sorteo). Only after the action completes are all processes released.
        """
        try:
            parse_end_message(msg)
            self._barrier.wait()
            write_frame(client_sock, ACK_OK)
        except multiprocessing.BrokenBarrierError:
            logging.info("action: fin_envio | result: interrupted | reason: shutdown")
        except Exception as e:
            logging.info(f"action: fin_envio | result: fail | error: {e}")
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass

    def __handle_query(self, client_sock, msg):
        """
        Handle QUERY message: return winners for the requesting agency.

        By the time a QUERY arrives, the process already passed barrier.wait() in
        __handle_end, so the sorteo is guaranteed to be complete.
        """
        try:
            agency = str(parse_query_message(msg))
            winners = self._winners_by_agency.get(agency, [])
            winners_payload = "{}|{}|{}".format(
                WINNERS_MSG_TYPE,
                len(winners),
                ",".join(winners),
            )
            write_frame(client_sock, winners_payload.encode("utf-8"))
            
            logging.info(
                f"action: query_procesada | result: success | cant_ganadores: {len(winners)}"
            )
        except Exception as e:
            logging.info(f"action: query_procesada | result: fail | error: {e}")
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass


    def __run_winners_by_agency(self):
        """
        Computes winners grouped by agency (runs as barrier action).

        Called exactly once by the last process to reach the barrier, while all
        other processes remain blocked. Populates winners_by_agency before
        any process is released.

        NOTE: We use a local dict to collect winners and then assign to the
        shared Manager dict, because nested lists in Manager dicts have
        synchronization issues when using .append() across processes.
        """

        # Aunque la barrera garantiza que solo uno entra acá, el Lock 
        # explicita la protección del recurso compartido (STORAGE y winners_by_agency)
        with self._bets_lock:
            local_winners = {}
            bets = list(load_bets())
            for bet in bets:
                if has_won(bet):
                    agency = str(bet.agency)
                    if agency not in local_winners:
                        local_winners[agency] = []
                    local_winners[agency].append(str(bet.document))
            
            for agency, winners_list in local_winners.items():
                self._winners_by_agency[agency] = winners_list

            logging.info("action: sorteo | result: success")

    def __shutdown(self, timeout=10):
        """
        Graceful shutdown: cierra sockets de clientes, termina procesos hijos, cleanup Manager.
        
        El flujo de shutdown es:
        1. Abortar la barrera para desbloquear procesos esperando en barrier.wait()
        2. Cerrar sockets de clientes para desbloquear procesos esperando en read_frame()
        3. Enviar SIGTERM a procesos hijos (via terminate())
        4. Esperar a que terminen
        5. NO usamos kill() - si un proceso no responde, lo logueamos pero no forzamos
        """

        # 1. Abortamos la barrera para desbloquear procesos hijos que estén esperando en barrier.wait()
        try:
            self._barrier.abort()
        except Exception:
            pass

        # 2. Cerramos los sockets de clientes para desbloquear hijos que estén en read_frame()
        for client_sock in self._client_sockets:
            try:
                client_sock.shutdown(socket.SHUT_RDWR)
                client_sock.close()
            except OSError:
                pass
        self._client_sockets.clear()

        # 3. Terminamos todos los procesos hijos (envía SIGTERM)
        for process in self._child_processes:
            if process.is_alive():
                process.terminate()
        
        # 4. Esperamos a que mueran
        for process in self._child_processes:
            process.join(timeout)
            if process.is_alive():
                # Si sigue vivo después del timeout, lo logueamos pero NO usamos kill()
                # El proceso eventualmente morirá cuando el container se detenga
                logging.warning(f"action: process_termination | result: timeout | pid: {process.pid}")
        
        # 5. Limpiamos la lista de procesos
        self._child_processes.clear()
        
        # 6. Cerramos el socket del server (ya debería estar cerrado por _handle_sigterm)
        try:
            self._server_socket.close()
        except OSError:
            pass
        
        # 7. Shutdown del manager
        try:
            self._manager.shutdown()
        except Exception as e:
            logging.warning(f"Manager shutdown error: {e}")
        
        logging.info("action: shutdown | result: success")
