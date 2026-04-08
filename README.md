## Autores

| Nombre         | Apellido      | Mail                  | Padrón |
| -------------- | ------------- | --------------------- | ------ |
| Ian            | von der Heyde | ivon@fi.uba.ar        | 107638 |

## Estructura del Proyecto

El desarrollo de este Trabajo Práctico se realizó de forma **iterativa y modular**, cumpliendo con la consigna de mantener una rama independiente por cada ejercicio.

Cada rama contiene su propia documentación específica en el `README.md` detallando los cambios correspondientes a ese nivel.

> Nota para la corrección: Para evaluar el sistema en su estado final y más robusto, se recomienda posicionarse en la rama `ej8`.

# TP0: Docker + Comunicaciones + Concurrencia


## Parte 3: Repaso de Concurrencia
En este ejercicio es importante considerar los mecanismos de sincronización a utilizar para el correcto funcionamiento de la persistencia.

### Ejercicio N°8:

Modificar el servidor para que permita aceptar conexiones y procesar mensajes en paralelo. En caso de que el alumno implemente el servidor en Python utilizando _multithreading_,  deberán tenerse en cuenta las [limitaciones propias del lenguaje](https://wiki.python.org/moin/GlobalInterpreterLock).

---

## Cambios Implementados

### Cliente y Servidor: De Secuencial a Multiprocessing + Conexiones Persistentes

#### Antes (Ejercicio 7)
- **Cliente**: Abría y cerraba **una conexión TCP nueva para cada batch** enviado.
  - Secuencia: `socket.Dial()` → `enviar batch` → `socket.Close()` → `socket.Dial()` → `enviar siguiente batch` → ...
  
- **Servidor**: Procesaba **un cliente por vez** (secuencial).
  - Aceptaba conexión, procesaba mensajes, cerraba conexión.
  - Siguiente cliente esperaba que termine el anterior.

#### Después (Ejercicio 8)

**Cliente**:
- Abre **UNA SOLA conexión TCP** al inicio.
- Mantiene la misma conexión para:
  - Enviar todos los batches 
  - Notificar END
  - Consultar ganadores
- Cierra conexión al final (`conn.Close()`).
- **Ventaja**: Eliminamos overhead de repetidas conexiones TCP.
- **Lectura streaming**: El CSV se lee línea por línea con `csv.Reader` en `sendBatches`, envía el batch y se queda esperando una respuesta antes de leer la próxima línea. 

**Servidor**:
- Usa `multiprocessing.Process` para que **cada cliente tenga su propio proceso hijo**.
- Main loop (`run()`):
  - Acepta conexiones continuamente
  - Por cada conexión → crea nuevo proceso worker
  - Los procesos hijo corren **en paralelo** (sin GIL).
- Cada worker (`__handle_client_connection`):
  - Loop infinito: lee mensajes de la misma conexión TCP
  - Dispatch a handlers BATCH/END/QUERY
  - Comparte estado via `multiprocessing.Manager()`

#### ¿Por qué Multiprocessing y no Threading?

Python tiene el **GIL (Global Interpreter Lock)**, que impide que múltiples threads ejecuten código Python simultáneamente. Esto significa:
- Con `threading`: solo un thread ejecuta bytecode Python a la vez → no hay paralelismo real.
- Con `multiprocessing`: cada proceso tiene su propio Python interpreter → paralelismo verdadero.

#### Nota técnica: Python moderno, GIL y decisión de arquitectura
En versiones actuales de CPython, el modelo por defecto todavía usa GIL.
Desde Python 3.13 existe una variante free-threaded (sin GIL) habilitada como build opcional, no como configuración estándar.
Esa variante todavía tiene adopción parcial del ecosistema y puede implicar diferencias de rendimiento o compatibilidad en extensiones nativas.
Si en el futuro el entorno objetivo usa de forma estable Python sin GIL, una solución multithreading podría volver a ser muy competitiva por menor overhead de creación/sincronización respecto de procesos.



### Graceful Shutdown

**Servidor**:
- Handler de SIGTERM cierra el socket del servidor para desbloquear `accept()`
- En shutdown:
  1. Aborta la barrera (`barrier.abort()`)
  2. Cierra sockets de clientes → hijos detectan EOF y salen de su loop limpiamente
  3. Espera a los hijos con `join(timeout)`
  4. `terminate()` sobre cualquier hijo que no haya salido (SIGTERM como último recurso, NO usa `kill()`)
- Los hijos usan `signal.SIG_DFL` para SIGTERM, de modo que `terminate()` del padre sea efectivo si es necesario.

**Cliente**:
- Goroutine que escucha SIGTERM
- Cierra conexión y notifica al loop principal via channel

---

## Decisiones de Diseño

### Protocolo de Comunicación

**Framing binario**:
```
[2 bytes big-endian: len(payload)][payload string UTF-8]
```
**MTU**: Se definió un límite de `8kB` bytes por frame (configurable via `protocol.maxPayloadSize` en config.yaml)

**Mensajes**:
| Tipo | Formato | Dirección | Respuesta |
|------|---------|-----------|-----------|
| BATCH | `BATCH\n agency\|name1\|name2\|doc\|date\|number\n...` | Cliente → Servidor | `ACK\|OK` o `ACK\|FAIL` |
| END | `END\|agency_id` | Cliente → Servidor | `ACK\|OK` |
| QUERY | `QUERY\|agency_id` | Cliente → Servidor | `WINNERS\|count\|dni1,dni2,...` |

---

### Cliente

**Flujo**:
1. **Abre canal streaming** desde CSV `/data/agency-{ID}.csv`
2. **Abre TCP una sola vez** → `net.Dial("tcp", serverAddr)`
3. **Consume apuestas del channel y arma batches** (tamaño configurable y dinámico)
4. **Envía batches en loop** por la misma conexión
   - Espera `ACK|OK/FAIL` antes del siguiente
5. **Notifica END** → `END|agency_id`
   - El cliente queda bloqueado en `ReadFrame` esperando el `ACK|OK`
   - Del otro lado, el servidor está bloqueado en `barrier.wait()` hasta que todas las agencias enviaron su END
   - Una vez que el sorteo termina, la barrera libera al servidor, que envía el `ACK|OK` y desbloquea al cliente
6. **Consulta ganadores** → recibe `WINNERS|...` directamente (sorteo ya realizado)
7. **Cierra conexión** (`conn.Close()`)

**Batching Dinámico**: 
- El cliente no solo corta por `maxAmount` (apuestas), sino que implementa un cálculo dinámico de bytes en tiempo real. Si el acumulado de apuestas más el encabezado `BATCH\n` alcanza el `MaxPayloadSize`, el cliente cierra el batch y lo envía.

---

### Servidor

#### Main Loop (`run()`)
```
while self._running:
    client_sock, addr = accept()  # Bloqueante, sin timeout
    self._client_sockets.append(client_sock)
    Process(target=__handle_client_connection, args=(client_sock, addr))
    cada 5 conexiones → limpiar procesos muertos
```

**Sin timeout**: El socket se cierra desde el handler de SIGTERM para desbloquear.

#### Worker Process (`__handle_client_connection`)
- Corre en **proceso separado** 
- Ignora SIGTERM (solo padre maneja)
- Loop infinito: `frame = read_frame(socket)` → dispatch handlers
- Cierra socket si error o EOF (incluyendo cierre por el padre en shutdown)

#### Handlers

**`__handle_batch()`**:
- Parsea apuestas
- Adquiere `bets_lock` → `store_bets()` → libera lock
- Responde `ACK|OK` o `ACK|FAIL`

**`__handle_end()`**:
- Llama `barrier.wait()` → bloquea hasta que todas las N agencias llegaron
- El último proceso en llegar ejecuta `__run_winners_by_agency()` (action de la barrera), mientras los demás siguen bloqueados
- Una vez que el sorteo termina, la barrera libera a todos
- Responde `ACK|OK`

**`__handle_query()`**:
- El proceso ya pasó la barrera.
- Responde `WINNERS|count|dni1,dni2,...` directamente
- Loguea cantidad de ganadores

#### Shared State (via `multiprocessing.Manager()`)

| Variable | Tipo | Propósito |
|----------|------|---------|
| `bets_lock` | Lock | Protege `store_bets()` y la escritura de archivos de ganadores |
| `barrier` | Barrier(N) | Sincroniza los N workers; su `action` corre el sorteo exactamente una vez |

Los ganadores no se almacenan en un dict compartido en memoria. En cambio, el `action` de la barrera escribe un archivo `winners/winners_{agency}.txt` por agencia (streaming sobre el generador `load_bets()`, sin `list()`). Cuando un hijo recibe QUERY, lee ese archivo. Esto acota el uso de memoria a O(1) durante el sorteo y O(ganadores de esa agencia) durante la consulta, en lugar de O(total de apuestas) o O(total de ganadores de todas las agencias).


### Mecanismos de sincronización en el servidor

- `self._bets_lock` (Manager.Lock)
  - Protege escrituras concurrentes a `store_bets()` y la escritura de archivos de ganadores en `__run_winners_by_agency`.

- `self._barrier` (multiprocessing.Barrier(N, action=__run_winners_by_agency))
  - Cada proceso llama `barrier.wait()` al recibir el END de su agencia.
  - La barrera bloquea a todos hasta que los N procesos llegaron.
  - El último en llegar ejecuta el `action` (sorteo) mientras los demás permanecen bloqueados.
  - Una vez que el sorteo termina, todos los procesos son liberados simultáneamente.
  - Esto garantiza que ningún proceso responda una QUERY antes de que los resultados estén listos, sin necesidad de locks ni flags adicionales.
  - En shutdown, el padre llama `barrier.abort()` para desbloquear procesos que estén esperando, causando `BrokenBarrierError` que los hijos capturan y manejan.

- **Archivos de ganadores por agencia** (`winners/winners_{agency}.txt`)
  - El `action` de la barrera itera el generador `load_bets()` directamente (sin `list()`) y escribe el DNI de cada ganador en su archivo de agencia correspondiente. Consumo de memoria O(1) durante el sorteo.
  - Cuando un hijo recibe QUERY, lee el archivo de su agencia. Si no existe, la agencia no tiene ganadores.

- **Cierre de sockets de clientes en shutdown**
  - El padre mantiene lista de sockets de clientes (`self._client_sockets`)
  - En shutdown, cierra estos sockets con `shutdown()` + `close()`
  - Esto desbloquea a los hijos que están esperando en `read_frame()`
  - Los hijos detectan el cierre (OSError) y terminan limpiamente

---

## Configuración

### Cliente (`config.yaml`)
```yaml
server:
  address: "server:12345"
batch:
  maxAmount: 10
protocol:
  maxPayloadSize: 8192  # Tamaño máximo de payload en bytes
log:
  level: "INFO"
```

### Servidor
- `AGENCIES_EXPECTED`: Número de agencias esperadas (para la barrera)
- `MAX_PAYLOAD_SIZE`: se podría agregar la variable de entorno para configurar esto en el protocolo del lado del server también

---

## Cómo Probar

### Setup inicial
```bash
# Damos permisos al script
chmod +x generar-compose.sh

# Crear compose con 5 agencias
./generar-compose.sh docker-compose-5.yaml 5

# Levantar (servidor + 5 clientes)
make docker-compose-up FILE=docker-compose-5.yaml
```

### Ver logs en vivo
```bash
make docker-compose-logs FILE=docker-compose-5.yaml
```

### Verificaciones esperadas

**Servidor debe loguear exactamente UNA vez**:
```
action: sorteo | result: success
```

**Cada cliente reporta ganadores**:
```
action: consulta_ganadores | result: success | cant_ganadores: <N>
```

### Detener containers
```bash
make docker-compose-down FILE=docker-compose-5.yaml
# o
docker compose -f docker-compose-5.yaml down -t 10
```