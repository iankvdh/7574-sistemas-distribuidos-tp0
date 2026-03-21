# TP0: Docker + Comunicaciones + Concurrencia


### Ejercicio N°4:
Modificar servidor y cliente para que ambos sistemas terminen de forma _graceful_ al recibir la signal `SIGTERM`. Terminar la aplicación de forma _graceful_ implica que todos los _file descriptors_ (entre los que se encuentran archivos, sockets, threads y procesos) deben cerrarse correctamente antes que el thread de la aplicación principal muera. Loguear mensajes en el cierre de cada recurso (hint: Verificar que hace el flag `-t` utilizado en el comando `docker compose down`).


## Cambios implementados

### Servidor:
- Se agregó el flag `_running` para controlar el loop principal.
- Se captura la señal `SIGTERM` y se ejecuta `_handle_sigterm`:
  - Cierra el socket principal del servidor.
  - Itera sobre todos los clientes conectados y los cierra.
  - Loguea cada cierre de cliente y del servidor.
- El loop principal revisa `_running` y termina cuando se recibe `SIGTERM`.

### Cliente:
- Se creó un canal stop para comunicar la señal de shutdown.
- Se captura `SIGTERM` en una goroutine (thread aparte):
  - Cierra la conexión actual c.conn si existe.
  - Loguea el cierre de conexión y notifica al loop principal mediante stop.
- El loop principal revisa stop antes de cada conexión y durante el sleep entre mensajes, deteniendo la ejecución inmediatamente si se recibe `SIGTERM`.
- Se loguea cada mensaje enviado/recibido, así como la terminación del loop por señal o por completar todos los mensajes.


## Cómo probar

### Paso 1: Levantamos el servidor y cliente
```bash
make docker-compose-up FILE=docker-compose-dev.yaml
```

### Paso 2: Enviar señal `SIGTERM`
```bash
docker compose -f docker-compose-dev.yaml down -t 10
```
> El flag `-t 10` envía `SIGTERM` y espera hasta 10 segundos para terminar los containers


### Paso 3: Verificar los logs
```bash
make docker-compose-logs FILE=docker-compose-dev.yaml
```

#### Servidor:
    action: shutdown | result: in_progress | signal: `SIGTERM`
    action: shutdown | result: success | closed_client_ip: <IP>
    action: shutdown | result: success
#### Cliente:
    action: shutdown | result: in_progress | client_id: <ID>
    action: close_connection | result: success | client_id: <ID>
    action: loop_terminated | result: success | client_id: <ID>
