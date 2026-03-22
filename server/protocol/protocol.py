ACK_OK = b"ACK|OK"
ACK_FAIL = b"ACK|FAIL"

# read_exact lee exactamente 'size' bytes del socket.
# Si la conexión se cierra antes de completar la lectura, tira un error.
def read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("connection closed before reading expected bytes")
        data.extend(chunk)
    return bytes(data)

# read_frame lee un frame completo del socket con formato:
# [2 bytes de tamaño (big-endian)][payload]
def read_frame(sock):
    # Lee el header de 2 bytes que indica el tamaño
    header = read_exact(sock, 2)
    payload_size = int.from_bytes(header, byteorder="big")
    # Lee el payload completo según el tamaño indicado
    return read_exact(sock, payload_size)

# write_frame escribe un frame en el socket con formato:
# [2 bytes de tamaño (big-endian)][payload]
# Usa sendall para asegurarse de que se envíen todos los bytes.
def write_frame(sock, payload):
    # Valida que el payload entre en 2 bytes (uint16)
    if len(payload) > 65535:
        raise ValueError("payload too large")
    
    # Arma el header con el tamaño en big-endian y envía el header + payload
    header = len(payload).to_bytes(2, byteorder="big")
    sock.sendall(header + payload)
