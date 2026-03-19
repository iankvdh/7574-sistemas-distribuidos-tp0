#!/bin/bash

set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "Error: Se requieren 2 argumentos."
    echo "Uso: $0 <nombre_archivo_salida> <cantidad_clientes>"
    exit 1
fi

archivo_salida="$1"
cantidad_clientes="$2"

if ! [[ "$cantidad_clientes" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: <cantidad_clientes> debe ser un entero positivo (>= 1)."
    exit 1
fi

echo "Nombre del archivo de salida: $archivo_salida"
echo "Cantidad de clientes: $cantidad_clientes"

python3 mi-generador.py "$archivo_salida" "$cantidad_clientes"

echo "Archivo $archivo_salida generado con exito."