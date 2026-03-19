# TP0: Docker + Comunicaciones + Concurrencia

## Parte 1: Introducción a Docker
En esta primera parte del trabajo práctico se plantean una serie de ejercicios que sirven para introducir las herramientas básicas de Docker que se utilizarán a lo largo de la materia. El entendimiento de las mismas será crucial para el desarrollo de los próximos TPs.

### Ejercicio N°1:
Para mi solución aproveché la sugerencia de la consigna y creé el script `generar-compose.sh` que simplemente toma los argumentos ("Nombre del archivo de salida" y "Cantidad de clientes") y se los pasa a mi archivo python `mi-generador.py`. El mismo se encarga de generar un nuevo docker compose con el nombre pasado como argumento que respete el formato del `docker-compose-dev.yaml` pero genera tantos clientes como los pedidos.

#### Para Ejecutarlo usar:
Comenzamos dándole permisos al script:
```
chmod +x generar-compose.sh
```


Luego usamos el script:
```
./generar-compose.sh <archivo_de_salida> N

# Ejemplo:
./generar-compose.sh docker-compose-5-clientes.yaml 5
```


Una vez generado el docker compose lo corremos al igual que el original con:
```
make docker-compose-up FILE=<archivo_de_salida>

# Ejemplo:
make docker-compose-up FILE=docker-compose-5-clientes.yaml
```
Para ver sus logs correr:
```
make docker-compose-logs FILE=<archivo_de_salida>

# Ejemplo:
make docker-compose-logs FILE=docker-compose-5-clientes.yaml
```
Detenerlo:
```
make docker-compose-down FILE=<archivo_de_salida>

# Ejemplo:
make docker-compose-down FILE=docker-compose-5-clientes.yaml
```