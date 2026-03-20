#!/bin/bash

# Configuracion
SERVER_NAME="server"
SERVER_PORT="12345" 
MSG="ping"
NETWORK="tp0_testing_net"

# Ejecutamos netcat usando una imagen ligera (busybox) conectada a la misma red de docker de los ejercicios anteriores.
# -echo: mandamos el mensaje
# -docker run -i: Mantiene el STDIN abierto para que el echo llegue al contenedor.
# -docker run --rm: Borra el contenedor después de su ejecución.
# -nc: netcat conecta al server y puerto
# -w 2: timeout 2s
RESULT=$(echo "$MSG" | docker run -i --rm --network "$NETWORK" busybox nc -w 2 "$SERVER_NAME" "$SERVER_PORT")

if [ "$RESULT" = "$MSG" ]; then
    echo "action: test_echo_server | result: success"
    exit 0
else
    echo "action: test_echo_server | result: fail"
    exit 1
fi