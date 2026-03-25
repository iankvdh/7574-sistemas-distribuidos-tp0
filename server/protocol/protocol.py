ACK_OK = b"ACK|OK"
ACK_FAIL = b"ACK|FAIL"
MAX_PAYLOAD_SIZE = 8192

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
    if payload_size > MAX_PAYLOAD_SIZE:
            raise ValueError(f"Payload recibido excede el límite: {payload_size}")
    
    # Lee el payload completo según el tamaño indicado
    return read_exact(sock, payload_size)

# write_frame escribe un frame en el socket con formato:
# [2 bytes de tamaño (big-endian)][payload]
# Usa sendall para asegurarse de que se envíen todos los bytes.
def write_frame(sock, payload):
    # Valida que el payload no exceda MAX_PAYLOAD_SIZE bytes
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError(f"payload too large: {len(payload)} bytes (max: {MAX_PAYLOAD_SIZE})")
    
    # Arma el header con el tamaño en big-endian y envía el header + payload
    header = len(payload).to_bytes(2, byteorder="big")
    sock.sendall(header + payload)
