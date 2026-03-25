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



### Signal Handling para Procesos Hijo

**Cambio**: Los procesos hijo ahora ignoran SIGTERM (al inicio de `__handle_client_connection`):
```python
signal.signal(signal.SIGTERM, signal.SIG_IGN)
```

**Por qué**: 
- Docker envía SIGTERM a todos los procesos del contenedor.
- Sin esta línea, los procesos hijo herederían el handler del padre y intentarían ejecutar `__shutdown()`.
- Resultado: múltiples procesos cerrando Manager, matando procesos ajenos, etc.
- Ahora: solo el padre maneja shutdown, los hijos mueren limpiamente.

### Backoff Exponencial en Queries (Clientе)

**Cambio en `queryWinners()`**:
- Antes: Esperaba fijan **200ms** si recibía `ACK|WAIT`.
- Ahora: 
  - Comienza en **100ms**
  - Se duplica en cada WAIT (100ms → 200ms → 400ms → 800ms → 1600ms)
  - Cap máximo: **2 segundos**

**Razón**: Si el sorteo tarda, no queremos bombardear al servidor con queries cada 200ms. El backoff exponencial reduce carga innecesaria.

---

## Decisiones de Diseño

### Protocolo de Comunicación

**Framing binario** (sin cambios del Ejercicio 7):
```
[2 bytes big-endian: len(payload)][payload string UTF-8]
```
**MTU**: Se definió un límite estricto de `8kB (MaxPayloadSize)` bytes por frame (tanto el emisor como el receptor validan el tamaño del payload)

**Mensajes**:
| Tipo | Formato | Dirección | Respuesta |
|------|---------|-----------|-----------|
| BATCH | `BATCH\n agency\|name1\|name2\|doc\|date\|number\n...` | Cliente → Servidor | `ACK\|OK` o `ACK\|FAIL` |
| END | `END\|agency_id` | Cliente → Servidor | `ACK\|OK` |
| QUERY | `QUERY\|agency_id` | Cliente → Servidor | `WINNERS\|count\|dni1,dni2,...` o `ACK\|WAIT` |

---

### Cliente

**Flujo**:
1. **Carga apuestas** desde CSV `/data/agency-{ID}.csv` y mapea a estructuras Bet.
2. **Abre TCP una sola vez** → `net.Dial("tcp", serverAddr)`
3. **Divide en batches** (tamaño configurable y dinámico)
4. **Envía batches en loop** por la misma conexión
   - Espera `ACK|OK/FAIL` antes del siguiente
5. **Notifica END** → `END|agency_id`
6. **Consulta ganadores** en loop con backoff:
   - Si `ACK|WAIT` → duerme 100ms, 200ms, 400ms... (max 2s)
   - Si `WINNERS|...` → parsea y termina
7. **Cierra conexión** (`conn.Close()`)

**SIGTERM Handling**:
- Goroutine que escucha `syscall.SIGTERM`
- Activa canal `stop` para interrumpir loops
- Cierra socket cuello limpio

**Batching Dinámico**: 
- El cliente ya no solo corta por `maxAmount` (80 apuestas). Ahora implementa un cálculo dinámico de bytes en tiempo real. Si el acumulado de apuestas más el encabezado `BATCH\n` alcanza los `8kB (MaxPayloadSize)`, el cliente cierra el batch y lo envía, garantizando que nunca se viole el límite del protocolo.

---

### Servidor

#### Main Loop (`run()`)
```
while self._running:
    client_sock, addr = accept()
    Process(target=__handle_client_connection, args=(client_sock, addr))
    cada 5 conexiones → limpiar procesos muertos
```

**Timeout del socket**: 1 segundo (para que SIGTERM sea responsive)

#### Worker Process (`__handle_client_connection`)
- Corre en **proceso separado** 
- Ignora SIGTERM (solo padre maneja)
- Loop infinito: `frame = read_frame(socket)` → dispatch handlers
- Cierra socket si error o EOF

#### Handlers

**`__handle_batch()`**:
- Parsea apuestas
- Adquiere `bets_lock` → `store_bets()` → libera lock
- Responde `ACK|OK` o `ACK|FAIL`

**`__handle_end()`**:
- Marca agencia en `finished_agencies[agency] = 1`
- Si es la última agencia:
  - Adquiere `sorteo_lock` (double-check locking)
  - Si no ejecutado aún: `__run_winners_by_agency()`
  - Activa `sorteo_realizado = True`
  - Loguea: `action: sorteo | result: success`
- Responde `ACK|OK`

**`__handle_query()`**:
- Si `not sorteo_realizado.value`: responde `ACK|WAIT`
- Si completado: responde `WINNERS|count|dni1,dni2,...`
- Loguea cantidad de ganadores

#### Shared State (via `multiprocessing.Manager()`)

| Variable | Tipo | Propósito |
|----------|------|---------|
| `finished_agencies` | dict | `agency_id → 1` (tracking de quién terminó) |
| `winners_by_agency` | dict | `agency_id → [dni1, dni2, ...]` (cache) |
| `bets_lock` | Lock | Protege `store_bets()` |
| `sorteo_lock` | Lock | Protege sección crítica del sorteo |
| `sorteo_realizado` | Value('b') | Flag atómico (False/True) |


### Mecanismos de sincronización en el servidor

El servidor usa `multiprocessing.Manager()` para compartir estado entre procesos hijos. Esto evita race conditions sobre memoria compartida y permite que cada worker acceda ordenado a los datos.
- `self._bets_lock` (Lock)
  - Protege tanto la escritura (`store_bets`) como la lectura del sorteo (`load_bets`).

- `self._finished_agencies` (Manager.dict)
  - Marca qué agencias recibieron su `END`.
  - Se usa para saber si se puede disparar el sorteo.
  - Guardamos `agency` como string por consistencia con keys en `winners_by_agency`.

- `self._sorteo_lock` (Lock) + `self._sorteo_realizado` (Value('b'))
  - `sorteo_lock` protege la sección crítica donde se calcula una sola vez el sorteo.
  - Patrón double-check:
    1. Si `len(finished_agencies) == expected`, intenta entrar al lock.
    2. Dentro del lock, chequear `if not self._sorteo_realizado.value`.
    3. Si sigue falso, correr `__run_winners_by_agency`, luego `self._sorteo_realizado.value=True`.
  - Esto evita que dos procesos (caso de END concurrentes) ejecuten sorteo al mismo tiempo o más de una vez.

- `self._winners_by_agency` (Manager.dict) (cache de resultados)
  - Mapa de agency -> lista de DNI ganadores.
  - Se construye en `__run_winners_by_agency()` usando dict local y luego asigando por agencia para evitar problemas de `append` en listas compartidas.

- `signal.signal(signal.SIGTERM, signal.SIG_IGN)` en cada proceso hijo
  - Los hijos ignoran SIGTERM y evitan ejecutar `__shutdown()` individualmente.
  - El padre recibe SIGTERM, pone `_running=False`, y hace `__shutdown()` sincronizado.

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