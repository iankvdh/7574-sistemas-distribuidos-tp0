# TP0: Docker + Comunicaciones + Concurrencia


### Ejercicio N°6:
Modificar los clientes para que envíen varias apuestas a la vez (modalidad conocida como procesamiento por _chunks_ o _batchs_). 
Los _batchs_ permiten que el cliente registre varias apuestas en una misma consulta, acortando tiempos de transmisión y procesamiento.

La información de cada agencia será simulada por la ingesta de su archivo numerado correspondiente, provisto por la cátedra dentro de `.data/datasets.zip`.
Los archivos deberán ser inyectados en los containers correspondientes y persistido por fuera de la imagen (hint: `docker volumes`), manteniendo la convencion de que el cliente N utilizara el archivo de apuestas `.data/agency-{N}.csv` .

En el servidor, si todas las apuestas del *batch* fueron procesadas correctamente, imprimir por log: `action: apuesta_recibida | result: success | cantidad: ${CANTIDAD_DE_APUESTAS}`. En caso de detectar un error con alguna de las apuestas, debe responder con un código de error a elección e imprimir: `action: apuesta_recibida | result: fail | cantidad: ${CANTIDAD_DE_APUESTAS}`.

La cantidad máxima de apuestas dentro de cada _batch_ debe ser configurable desde config.yaml. Respetar la clave `batch: maxAmount`, pero modificar el valor por defecto de modo tal que los paquetes no excedan los 8kB. 

Por su parte, el servidor deberá responder con éxito solamente si todas las apuestas del _batch_ fueron procesadas correctamente.



## Cambios implementados

### Protocolo de comunicación
- Se mantiene framing binario para transporte en sockets:
  - `[2 bytes tamaño][payload]`.
  - **MTU**: Se definió un límite estricto de `8kB (MaxPayloadSize)` bytes por frame (tanto el emisor como el receptor validan el tamaño del payload)
- El payload de negocio para batches se define como:
  - `BATCH\n`
  - `agency|first_name|last_name|document|birthdate|number\n` (una línea por apuesta).
- Respuesta del servidor:
  - `ACK|OK` si todo el batch fue persistido.
  - `ACK|FAIL` si hubo error en alguna apuesta del batch.


### Cliente
- El cliente ya no toma una apuesta individual desde env vars para el envío.
- Carga apuestas desde el CSV de su agencia (`/data/agency.csv`) usando `LoadBetsFromCSV(...)`.
- Divide la lista en lotes con tamaño máximo configurable por `batch.maxAmount` (tamaño configurable y dinámico).
- Envía cada lote como un único mensaje y espera ACK/NACK del servidor.

**Batching Dinámico**: 
- El cliente ya no solo corta por `maxAmount` (80 apuestas). Ahora implementa un cálculo dinámico de bytes en tiempo real. Si el acumulado de apuestas más el encabezado `BATCH\n` alcanza los `8kB (MaxPayloadSize)`, el cliente cierra el batch y lo envía, garantizando que nunca se viole el límite del protocolo.  


### Servidor
- Recibe un mensaje batch por conexión.
- Parsea el payload con `parse_batch_message(...)`.
- Si todas las apuestas son válidas, persiste el lote con `store_bets(bets)` y responde `ACK|OK`.
- Si alguna apuesta falla, responde `ACK|FAIL`.
- Logs del enunciado para ejercicio 6:
  - `action: apuesta_recibida | result: success | cantidad: ${CANTIDAD_DE_APUESTAS}`
  - `action: apuesta_recibida | result: fail | cantidad: ${CANTIDAD_DE_APUESTAS}`


## Cómo probar

### Paso 1: Levantar servidor y 5 clientes
```bash
chmod +x generar-compose.sh
./generar-compose.sh docker-compose-5.yaml 5
make docker-compose-up FILE=docker-compose-5.yaml
```

> El compose generado monta automáticamente:
> - `./.data/dataset/agency-{N}.csv` en cada cliente N
> - como `/data/agency.csv` dentro del contenedor

### Paso 2: Ver los logs en tiempo real
```bash
make docker-compose-logs FILE=docker-compose-5.yaml
```
> Verificar al menos:

Servidor:
  action: apuesta_recibida | result: success | cantidad: <N>

Cliente:
  action: batch_enviado | result: success | cantidad: <N> | client_id: <ID>

### Paso 3: Detener containers
```bash
docker compose -f docker-compose-5.yaml down -t 10
o
make docker-compose-down FILE=docker-compose-5.yaml
```
> El flag `-t 10` da 10 segundos para cierre ordenado antes de forzar kill

