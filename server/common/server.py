import socket
import logging
import signal
import multiprocessing
import os

from common.bet_message import BatchParseError, parse_batch_message, parse_end_message, parse_query_message, BATCH_MSG_TYPE, END_MSG_TYPE, QUERY_MSG_TYPE, WINNERS_MSG_TYPE
from common.utils import has_won, load_bets, store_bets, STORAGE_FILEPATH
from protocol.protocol import read_frame, write_frame, ACK_OK, ACK_FAIL, ACK_WAIT


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
        
        # Estado compartido usando multiprocessing.Manager()
        self._manager = multiprocessing.Manager()
        self._finished_agencies = self._manager.dict()  # agencia -> 1 (solo para saber si ya terminó)
        self._winners_by_agency = self._manager.dict() # agencia -> [dni...]
        self._bets_lock = self._manager.Lock()  # Lock para store_bets()
        self._sorteo_lock = self._manager.Lock()  # Lock para proteger sección crítica del sorteo
        self._sorteo_realizado = self._manager.Value('b', False)  # Flag (ya se hizo o no)

    def _handle_sigterm(self):
        logging.info("action: shutdown | result: in_progress | signal: SIGTERM")
        self._running = False
        self.__shutdown(timeout=5)

    def run(self):
        """
        Main server loop with multiprocessing support.

        Accepts client connections and spawns a new process for each client.
        Each child process handles the persistent client connection.
        """
        # Handle SIGTERM signal
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        
        # Le ponemos un timeout al socket así el accept() no queda colgado eternamente y se revisa nuevamente el flag de self._running
        self._server_socket.settimeout(1)

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
                
                # Levantamos un proceso nuevo para manejar al cliente
                process = multiprocessing.Process(
                    target=self.__handle_client_connection,
                    args=(client_sock, addr[0])
                )
                process.start()
                self._child_processes.append(process)
                
            except socket.timeout:
                # Timeout, check self._running
                continue
            except OSError as e:
                if self._running:
                    logging.error(f"action: accept_connections | result: fail | error: {e}")
                break

        # Graceful shutdown
        self.__shutdown(timeout=5)

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
        Handle END message: mark agency as finished, trigger draw if all agencies done.
        """
        try:
            agency = str(parse_end_message(msg))
            
            # Marcamos la agencia como finalizada
            self._finished_agencies[agency] = 1
            
            if len(self._finished_agencies) == self._agencies_expected:
                with self._sorteo_lock:
                    if not self._sorteo_realizado.value: 
                        self.__run_winners_by_agency()
                    self._sorteo_realizado.value = True
                    logging.info("action: sorteo | result: success")
            
            write_frame(client_sock, ACK_OK)
        except Exception as e:
            logging.info(f"action: fin_envio | result: fail | error: {e}")
            try:
                write_frame(client_sock, ACK_FAIL)
            except OSError:
                pass

    def __handle_query(self, client_sock, msg):
        """
        Handle QUERY message: return winners if draw is complete, else WAIT.
        """
        try:
            agency = str(parse_query_message(msg))  # Asegurar string como clave
            
            # Si todavía no se hizo el sorteo, decimos que espere
            if not self._sorteo_realizado.value:
                write_frame(client_sock, ACK_WAIT)
                return
            
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
        Computes winners grouped by agency.

        Loads all stored bets, evaluates which bets have won, and builds
        an in-memory mapping in the shared state:

            agency -> list of winner document IDs
        
        This method is called ONLY ONCE when all agencies have notified
        that they finished sending bets.
        
        NOTE: We use a local dict to collect winners and then assign to the
        shared Manager dict, because nested lists in Manager dicts have
        synchronization issues when using .append() across processes.
        """
        # Juntamos ganadores en un dict local
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

    def __shutdown(self, timeout=5):
        """
        Graceful shutdown: terminate child processes, cleanup Manager, and close server socket.
        """
        logging.info("action: shutdown | result: in_progress")
        
        # Terminamos todos los procesos hijos
        for process in self._child_processes:
            if process.is_alive():
                process.terminate()
        
        # Esperamos un poco a que mueran
        for process in self._child_processes:
            process.join(timeout)
            if process.is_alive():
                # Si sigue vivo, lo matamos de una
                process.kill()
                process.join()
        
        # Cerramos el socket del server
        try:
            self._server_socket.close()
        except OSError:
            pass
        
        try:
            self._manager.shutdown()
        except Exception as e:
            logging.warning(f"Manager shutdown error: {e}")
        
        logging.info("action: shutdown | result: success")
