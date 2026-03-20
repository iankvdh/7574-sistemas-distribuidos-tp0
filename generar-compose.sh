#!/bin/bash

set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "Error: Se requieren 2 argumentos."
    echo "Uso: $0 <nombre_archivo_salida> <cantidad_clientes>"
    exit 1
fi

archivo_salida="$1"
cantidad_clientes="$2"


echo "Nombre del archivo de salida: $archivo_salida"
echo "Cantidad de clientes: $cantidad_clientes"

python3 mi-generador.py "$archivo_salida" "$cantidad_clientes"

echo "Archivo $archivo_salida generado con exito."