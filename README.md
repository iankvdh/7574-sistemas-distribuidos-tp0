# TP0: Docker + Comunicaciones + Concurrencia


### Ejercicio N°7:

Modificar los clientes para que notifiquen al servidor al finalizar con el envío de todas las apuestas y así proceder con el sorteo.
Inmediatamente después de la notificacion, los clientes consultarán la lista de ganadores del sorteo correspondientes a su agencia.
Una vez el cliente obtenga los resultados, deberá imprimir por log: `action: consulta_ganadores | result: success | cant_ganadores: ${CANT}`.

El servidor deberá esperar la notificación de las 5 agencias para considerar que se realizó el sorteo e imprimir por log: `action: sorteo | result: success`.
Luego de este evento, podrá verificar cada apuesta con las funciones `load_bets(...)` y `has_won(...)` y retornar los DNI de los ganadores de la agencia en cuestión. Antes del sorteo no se podrán responder consultas por la lista de ganadores con información parcial.

Las funciones `load_bets(...)` y `has_won(...)` son provistas por la cátedra y no podrán ser modificadas por el alumno.

No es correcto realizar un broadcast de todos los ganadores hacia todas las agencias, se espera que se informen los DNIs ganadores que correspondan a cada una de ellas.


## Cambios implementados

### Implementación de sincronización del sorteo

El servidor implementa un mecanismo de sincronización para garantizar que:

1. **Espera a todas las agencias**: El servidor cuenta las notificaciones `END` y solo ejecuta el sorteo cuando **todas las agencias esperadas** han notificado que terminaron.

2. **Sorteo único**: El método `__run_winners_by_agency()` se ejecuta **una única vez** cuando la última agencia notifica `END`.

3. **Bloqueo de consultas prematuras**: Antes de que el sorteo esté completo, todas las consultas `QUERY` reciben `ACK|WAIT`, sin importar si la agencia ya notificó `END` o no.

4. **Configuración dinámica**: El número de agencias esperadas se configura mediante:
   - Variable de entorno `AGENCIES_EXPECTED` (generada automáticamente por `generar-compose.sh`)
   - Valor por defecto en `server/config.ini`: `AGENCIES_EXPECTED = 5`

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
- Recibe un mensaje batch por conexión.
- Parsea el payload con `parse_batch_message(...)`.
- Si todas las apuestas son válidas, persiste el lote con `store_bets(bets)` y responde `ACK|OK`.
- Si alguna apuesta falla, responde `ACK|FAIL`.
- Mantiene el estado de agencias que notificaron fin de envío (`END`).
- **Sincronización del sorteo**:
  - Cuenta las notificaciones `END` de cada agencia
  - Cuando **todas las agencias esperadas** han notificado, ejecuta el sorteo **una única vez**
  - Loguea: `action: sorteo | result: success`
- Responde consultas de ganadores por agencia (`QUERY`):
  - **Antes del sorteo completo**: `ACK|WAIT`
  - **Después del sorteo**: `WINNERS|count|dni1,dni2,...` con los ganadores de esa agencia
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

