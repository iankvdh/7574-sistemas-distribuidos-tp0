# TP0: Docker + Comunicaciones + Concurrencia


## Parte 2: Repaso de Comunicaciones

Las secciones de repaso del trabajo práctico plantean un caso de uso denominado **Lotería Nacional**. Para la resolución de las mismas deberá utilizarse como base el código fuente provisto en la primera parte, con las modificaciones agregadas en el ejercicio 4.

### Ejercicio N°5:
Modificar la lógica de negocio tanto de los clientes como del servidor para nuestro nuevo caso de uso.

#### Cliente
Emulará a una _agencia de quiniela_ que participa del proyecto. Existen 5 agencias. Deberán recibir como variables de entorno los campos que representan la apuesta de una persona: nombre, apellido, DNI, nacimiento, numero apostado (en adelante 'número'). Ej.: `NOMBRE=Santiago Lionel`, `APELLIDO=Lorca`, `DOCUMENTO=30904465`, `NACIMIENTO=1999-03-17` y `NUMERO=7574` respectivamente.

Los campos deben enviarse al servidor para dejar registro de la apuesta. Al recibir la confirmación del servidor se debe imprimir por log: `action: apuesta_enviada | result: success | dni: ${DNI} | numero: ${NUMERO}`.



#### Servidor
Emulará a la _central de Lotería Nacional_. Deberá recibir los campos de la cada apuesta desde los clientes y almacenar la información mediante la función `store_bet(...)` para control futuro de ganadores. La función `store_bet(...)` es provista por la cátedra y no podrá ser modificada por el alumno.
Al persistir se debe imprimir por log: `action: apuesta_almacenada | result: success | dni: ${DNI} | numero: ${NUMERO}`.

#### Comunicación:
Se deberá implementar un módulo de comunicación entre el cliente y el servidor donde se maneje el envío y la recepción de los paquetes, el cual se espera que contemple:
* Definición de un protocolo para el envío de los mensajes.
* Serialización de los datos.
* Correcta separación de responsabilidades entre modelo de dominio y capa de comunicación.
* Correcto empleo de sockets, incluyendo manejo de errores y evitando los fenómenos conocidos como [_short read y short write_](https://cs61.seas.harvard.edu/site/2018/FileDescriptors/).



## Cambios implementados

### Protocolo de comunicación
- Se definió un frame binario de tamaño fijo para el header: `[2 bytes tamaño][payload]`.
- El tamaño se codifica en big-endian (`uint16`) y luego se leen/escriben exactamente esos bytes.
- Con este esquema se evitan `short read` y `short write` tanto en cliente como en servidor.

Formato de payload para apuestas:
- `BET|agency|first_name|last_name|document|birthdate|number`

Confirmación del servidor:
- `ACK|OK` (también en frame binario)

### Cliente
- Se agregó el modelo `Bet` en `client/common/bet.go` para separar dominio de comunicación.
- `Bet` incluye `agency`, `first_name`, `last_name`, `document`, `birthdate` y `number`.
- Las variables de entorno agregadas son:`NOMBRE`, `APELLIDO`, `DOCUMENTO`, `NACIMIENTO`, `NUMERO`.
- El payload de la apuesta se arma en `buildBetMessage()` dentro del modelo.
- El envío/recepción del frame usa `WriteFrame()` y `ReadFrame()` en `client/protocol/protocol.go`.
- Al recibir `ACK`, el cliente loguea:
  `action: apuesta_enviada | result: success | dni: ${DNI} | numero: ${NUMERO}`

### Servidor
- Se implementó lectura/escritura de frame en `server/protocol/protocol.py` (`read_frame` / `write_frame`).
- El parseo del mensaje de negocio `BET|agency|first_name|last_name|document|birthdate|number` se hace en `server/common/bet_message.py`.
- Se persiste con `store_bets([bet])`.
- Se envía respuesta `ACK|OK` en frame binario.
- Al persistir se loguea:
  `action: apuesta_almacenada | result: success | dni: ${DNI} | numero: ${NUMERO}`

### De dónde sale el número de agencia
- En `mi-generador.py`, cada cliente se crea con una variable `CLI_ID` distinta (`1..N`).
- Ese valor se toma en el cliente como `id` y se usa como `agency` dentro de la apuesta.

## Cómo probar

### Paso 1: Levantar servidor y 5 clientes
```bash
chmod +x generar-compose.sh
./generar-compose.sh docker-compose-5.yaml 5
make docker-compose-up FILE=docker-compose-5.yaml
```

### Paso 2: Ver los logs en tiempo real
```bash
make docker-compose-logs FILE=docker-compose-5.yaml
```
> Verificar al menos:

Servidor:
  action: apuesta_almacenada | result: success | dni: <DNI> | numero: <NUMERO>

Cliente:
  action: apuesta_enviada | result: success | dni: <DNI> | numero: <NUMERO>

### Paso 3: Detener containers
```bash
docker compose -f docker-compose-5.yaml down -t 10
o
make docker-compose-down FILE=docker-compose-5.yaml
```
> El flag `-t 10` da 10 segundos para cierre ordenado antes de forzar kill

