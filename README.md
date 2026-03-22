# TP0: Docker + Comunicaciones + Concurrencia


## Parte 3: Repaso de Concurrencia
En este ejercicio es importante considerar los mecanismos de sincronización a utilizar para el correcto funcionamiento de la persistencia.

### Ejercicio N°8:

Modificar el servidor para que permita aceptar conexiones y procesar mensajes en paralelo. En caso de que el alumno implemente el servidor en Python utilizando _multithreading_,  deberán tenerse en cuenta las [limitaciones propias del lenguaje](https://wiki.python.org/moin/GlobalInterpreterLock).

### Consideraciones sobre GIL y diseño elegido
- Python (CPython) usa GIL, por lo que los hilos no paralelizan bien trabajo puramente CPU-bound.
- En este TP, el servidor es principalmente I/O-bound (sockets y acceso a archivo), por lo que _multithreading_ sigue siendo una opción válida y efectiva para escalar conexiones concurrentes.
- Para evitar corrupción de datos en persistencia y condiciones de carrera en estado compartido, se agregaron locks explícitos.



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
- Acepta conexiones en paralelo y crea un thread por cliente.
- Recibe un mensaje batch por conexión.
- Parsea el payload con `parse_batch_message(...)`.
- Si todas las apuestas son válidas, persiste el lote con `store_bets(bets)` y responde `ACK|OK`.
- Si alguna apuesta falla, responde `ACK|FAIL`.
- Mantiene el estado de agencias que notificaron fin de envío (`END`).
- Cuando llega `END` de una agencia, recalcula ganadores y loguea:
  - `action: sorteo | result: success`
- Responde consultas de ganadores por agencia (`QUERY`):
  - Si la agencia aún no notificó `END`: `ACK|WAIT`
  - Si la agencia ya notificó `END`: `WINNERS|count|...`
- Sincronización aplicada:
  - `storage_lock`: serializa escritura/lectura de `STORAGE_FILEPATH`.
  - `state_lock`: protege estructuras compartidas (`finished_agencies`, `winners_by_agency`).
  - `clients_lock`: protege altas/bajas de sockets y lista de threads.
- Logs principales:
  - `action: apuesta_recibida | result: success | cantidad: ${CANTIDAD_DE_APUESTAS}`
  - `action: apuesta_recibida | result: fail | cantidad: ${CANTIDAD_DE_APUESTAS}`
  - `action: sorteo | result: success`


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

