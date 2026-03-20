# TP0: Docker + Comunicaciones + Concurrencia

### Ejercicio N°3:
Crear un script de bash `validar-echo-server.sh` que permita verificar el correcto funcionamiento del servidor utilizando el comando `netcat` para interactuar con el mismo. Dado que el servidor es un echo server, se debe enviar un mensaje al servidor y esperar recibir el mismo mensaje enviado.

En caso de que la validación sea exitosa imprimir: `action: test_echo_server | result: success`, de lo contrario imprimir:`action: test_echo_server | result: fail`.

El script deberá ubicarse en la raíz del proyecto. Netcat no debe ser instalado en la máquina _host_ y no se pueden exponer puertos del servidor para realizar la comunicación (hint: `docker network`). `


## Cambios implementados

### Archivos

- **validar-echo-server.sh**: Script de Bash que implementa lo pedido. Usa una imagen ligera de Docker (busybox) para ejecutar netcat dentro de la misma red que el servidor, cumpliendo con la restricción de no instalar dependencias en el host ni exponer puertos.

## Cómo probar

### Paso 1: Levantamos el servidor (aunque este comando tambien levanta a un cliente pero no importa)
```bash
make docker-compose-up
```

### Paso 2: Ejecutar la validación manual

Con el servidor corriendo, ejecutamos el script de validación desde la raíz del proyecto:

```bash
chmod +x validar-echo-server.sh
./validar-echo-server.sh
```

### Paso 3: Verificar los logs

```bash
docker compose -f docker-compose-test.yaml logs -f
```
