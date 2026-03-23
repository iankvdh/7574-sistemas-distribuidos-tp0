# TP0: Docker + Comunicaciones + Concurrencia


## Parte 3: Repaso de Concurrencia
En este ejercicio es importante considerar los mecanismos de sincronización a utilizar para el correcto funcionamiento de la persistencia.

### Ejercicio N°8:

Modificar el servidor para que permita aceptar conexiones y procesar mensajes en paralelo. En caso de que el alumno implemente el servidor en Python utilizando _multithreading_,  deberán tenerse en cuenta las [limitaciones propias del lenguaje](https://wiki.python.org/moin/GlobalInterpreterLock).

### Consideraciones sobre GIL y diseño elegido
- Python (CPython) usa GIL, por lo que los hilos no paralelizan bien trabajo puramente CPU-bound.
- Para evitar esa limitación y preparar el servidor para cargas grandes, la implementación usa _multiprocessing_ (un proceso worker por conexión).
- La sincronización sobre estado compartido y persistencia se resuelve con locks multiprocess.

### Nota sobre la arquitectura de procesos vs. hilos
- Si bien esta versión utiliza _multiprocessing_ para garantizar paralelismo real frente al GIL, aclaro que me siento mucho más cómodo con la simpleza de mi versión anterior _multithreading_ que tiene una lógica más simple y legible (se puede ver en mi commit anterior `Commit c04f5e9` - `feat (ej8): se completó el ejercicio 8`)

### Por qué multiprocessing en esta versión
- Se eligió _multiprocessing_ para escalar mejor frente a cargas muy grandes y evitar depender del paralelismo limitado por GIL.
- El servidor acepta conexiones en el proceso principal y delega cada conexión a un proceso worker.
- Se evitó recalcular ganadores recorriendo todos los registros en memoria: los documentos ganadores se persisten incrementalmente durante la recepción de cada batch.

### Nota técnica: Python moderno, GIL y decisión de arquitectura
- En versiones actuales de CPython, el modelo por defecto todavía usa GIL.
- Desde Python 3.13 existe una variante free-threaded (sin GIL) habilitada como build opcional, no como configuración estándar.
- Esa variante todavía tiene adopción parcial del ecosistema y puede implicar diferencias de rendimiento o compatibilidad en extensiones nativas.
- Si en el futuro el entorno objetivo usa de forma estable Python sin GIL, una solución multithreading como la del commit anterior podría volver a ser muy competitiva por menor overhead de creación/sincronización respecto de procesos.


## Cambios implementados

### Protocolo de comunicación
- Se mantiene framing binario para transporte en sockets:
  - `[2 bytes tamaño][payload]`.
- El payload de negocio para apuestas por lote se define como:
  - `BATCH\n`
  - `agency|first_name|last_name|document|birthdate|number\n` (una línea por apuesta).
- Mensajes de control agregados para ejercicio 7:
  - `END|agency` (notificación de fin de envíos)
  - `QUERY|agency` (consulta de ganadores de la agencia)
- Respuestas del servidor:
  - `ACK|OK` si todo el batch fue persistido.
  - `ACK|FAIL` si hubo error en alguna apuesta del batch.
  - `ACK|WAIT` si llega una consulta antes de que se complete el sorteo.
  - `WINNERS|count|dni1,dni2,...` para responder ganadores por agencia.


### Cliente
- Carga apuestas desde el CSV de su agencia (`/data/agency-{ID}.csv`) usando `LoadBetsFromCSV(...)`.
- Divide la lista en lotes con tamaño máximo configurable por `batch.maxAmount`.
- Envía cada lote como un único mensaje y espera ACK/NACK del servidor.
- Al terminar de enviar todos los lotes, envía `END|agency` al servidor.
- Luego realiza `QUERY|agency` hasta recibir una respuesta de ganadores.
- Cuando obtiene la respuesta final, loguea:
  - `action: consulta_ganadores | result: success | cant_ganadores: ${CANT}`


### Servidor
- Acepta conexiones en paralelo y crea un proceso worker por cliente.
- Limita la concurrencia con `max_workers` (configurable por `SERVER_MAX_WORKERS`) para evitar creación ilimitada de procesos.
- Recibe un mensaje batch por conexión.
- Parsea el payload con `parse_batch_message(...)`.
- Si todas las apuestas son válidas, persiste el lote con `store_bets(bets)` y, en la misma operación, persiste solo los ganadores del lote por agencia.
- Si alguna apuesta falla, responde `ACK|FAIL`.
- Mantiene el estado de agencias que notificaron fin de envío (`END`).
- Cuando llega `END` de una agencia, marca agencia finalizada y loguea:
  - `action: sorteo | result: success`
- Responde consultas de ganadores por agencia (`QUERY`):
  - Si la agencia aún no notificó `END`: `ACK|WAIT`
  - Si la agencia ya notificó `END`: `WINNERS|count|dni1,dni2,...`
- Sincronización aplicada:
  - `bets_file_lock`: serializa la escritura de `STORAGE_FILEPATH`.
  - `winners_file_locks` (lock striping): sincroniza accesos a archivos de ganadores por agencia y reduce contención entre agencias distintas.
  - `finished_agencies_lock`: protege estructuras compartidas de agencias finalizadas.
  - `worker_processes_lock`: protege la lista de procesos workers.
  - `worker_slots` (semáforo): limita la cantidad de workers activos en simultáneo.

### Detalle: Lock Striping y parámetro 16
- `winners_file_locks` usa una técnica de lock striping: en lugar de un lock global para todos los archivos de ganadores, se mantiene un pool de 16 locks.
- Cada agencia se mapea de forma determinística a un lock con un hash estable (`blake2b`) y módulo 16.
- Esto permite que agencias distintas escriban/lean en paralelo cuando caen en locks diferentes, reduciendo la contención frente a un lock único.
- El valor 16 es un equilibrio práctico: evita el serializado total (1) sin sobredimensionar la cantidad de locks (valores muy altos).

### Detalle: cómo funciona el reap de workers
- El servidor guarda referencias a procesos hijos en `worker_processes`.
- En cada iteración del loop principal ejecuta `__reap_finished_workers()`.
- Ese método filtra procesos vivos y elimina/`join()` los finalizados, evitando crecimiento indefinido de la lista y acumulación de procesos zombie.
- En shutdown, se hace un `join(timeout)` final y, si algún proceso sigue vivo, `terminate()` para cierre ordenado.

### Límite de concurrencia para miles de agencias
- El servidor no crea procesos de forma infinita: antes de aceptar y despachar una conexión, adquiere un slot de `worker_slots`.
- Si se alcanza `max_workers`, el loop principal espera a que un worker termine y libere su slot.
- Mientras tanto, las nuevas conexiones quedan esperando en el backlog TCP (`SERVER_LISTEN_BACKLOG`) en lugar de disparar más procesos.
- Esto reduce riesgo de agotamiento de memoria y exceso de context-switch bajo picos de carga.



## Cómo probar

### Paso 1: Levantar servidor y 5 clientes
```bash
chmod +x generar-compose.sh
./generar-compose.sh docker-compose-5.yaml 5
make docker-compose-up FILE=docker-compose-5.yaml
```

> El compose generado monta automáticamente:
> - `./.data/agency-{N}.csv` en cada cliente N
> - como `/data/agency-{N}.csv` dentro del contenedor

### Paso 2: Ver los logs en tiempo real
```bash
make docker-compose-logs FILE=docker-compose-5.yaml
```
> Verificar:

+ **Servidor**: `action: sorteo | result: success`

+ **Cliente**: `action: consulta_ganadores | result: success | cant_ganadores: <CANT>`

### Paso 3: Detener containers
```bash
docker compose -f docker-compose-5.yaml down -t 10
o
make docker-compose-down FILE=docker-compose-5.yaml
```
> El flag `-t 10` da 10 segundos para cierre ordenado antes de forzar kill

