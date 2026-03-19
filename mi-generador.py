import sys


def generar_compose(archivo_de_salida, cantidad_de_clientes):
    contenido = """name: tp0
services:
  server:
    container_name: server
    image: server:latest
    entrypoint: python3 /main.py
    volumes:
      - ./server/config.ini:/config.ini:ro
    environment:
      - PYTHONUNBUFFERED=1
    networks:
      - testing_net

"""

    for cliente in range(1, cantidad_de_clientes + 1):
        contenido += f"""  client{cliente}:
    container_name: client{cliente}
    image: client:latest
    entrypoint: /client
    volumes:
      - ./client/config.yaml:/config.yaml:ro
    environment:
      - CLI_ID={cliente}
    networks:
      - testing_net
    depends_on:
      - server

"""

    contenido += """networks:
  testing_net:
    ipam:
      driver: default
      config:
        - subnet: 172.25.125.0/24
"""

    with open(archivo_de_salida, "w") as f:
        f.write(contenido)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python3 mi-generador.py <archivo_salida> <cantidad_clientes>")
    else:
        generar_compose(sys.argv[1], int(sys.argv[2]))
