# TP0: Docker + Comunicaciones + Concurrencia

### Ejercicio N°2:
Modificar el cliente y el servidor para lograr que realizar cambios en el archivo de configuración no requiera reconstruír las imágenes de Docker para que los mismos sean efectivos. La configuración a través del archivo correspondiente (`config.ini` y `config.yaml`, dependiendo de la aplicación) debe ser inyectada en el container y persistida por fuera de la imagen (hint: `docker volumes`).


## Cambios implementados

### Archivos modificados

- **`docker-compose-dev.yaml` y `mi-generador.py`**

    Los archivos `docker-compose-dev.yaml` y `mi-generador.py` ahora
    incluyen:

    ``` yaml
    volumes:
    - ./server/config.ini:/config.ini:ro
    - ./client/config.yaml:/config.yaml:ro
    ```

    > **Nota:** El sufijo `:ro` significa "read-only" (solo lectura) desde el
    contenedor.


    Además se eliminaron las líneas `- LOGGING_LEVEL=DEBUG` y
    `- CLI_LOG_LEVEL=DEBUG` para poder editar el LOG_LEVEL desde
    configuración y que no los tome desde el compose.

- **Dockerfile**

    Por último se quitó la linea `COPY ./client/config.yaml /config.yaml`
    del Dockerfile del cliente. Esto garantiza que la aplicación no utilice
    una configuración "congelada" dentro de la imagen al momento del build,
    obligando al contenedor a obtener la configuración en tiempo de
    ejecución a través del volumen montado.

## Cómo probar

### Paso 1: Levantar el sistema

``` bash
make docker-compose-up FILE=docker-compose-dev.yaml
```

### Paso 2: Modificar configuración

Edita `server/config.ini` o `client/config.yaml`. Cambia, por ejemplo,
el log level o el puerto.

### Paso 3: Reiniciar sin intervención de Makefile

Para demostrar que la imagen no se toca, reinicia los contenedores
directamente con Docker (ya que el Makefile hace build nuevamente):

``` bash
docker compose -f docker-compose-dev.yaml restart
```

### Paso 4: Verificar los cambios

``` bash
docker compose -f docker-compose-dev.yaml logs -f
```

Los logs mostrarán la nueva configuración aplicada sin haber
reconstruido la imagen.

### Paso 5: Confirmación de "No Rebuild"

Si comparas el ID de la imagen antes y después, verás que no cambia:

``` bash
# ID antes del cambio
docker inspect server:latest --format='{{.ID}}'

# (Edita config, reinicia)

# ID después del cambio
docker inspect server:latest --format='{{.ID}}'

# Las IDs deben ser iguales (la imagen no se reconstruyó)
```

## Con generador de compose

### Uso con mi-generador.py

Lo mismo aplica a compose generados con `mi-generador.py`:

``` bash
./generar-compose.sh docker-compose-test.yaml 5
make docker-compose-up FILE=docker-compose-test.yaml

# Editar configs...

# Reiniciar sin rebuild
docker compose -f docker-compose-test.yaml restart

# Verificar
docker compose -f docker-compose-test.yaml logs -f
```