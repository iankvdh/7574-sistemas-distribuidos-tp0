package protocol

import (
	"encoding/binary"
	"fmt"
	"io"
)

const (
	ExpectedACK     = "ACK|OK"
	ExpectedNACK    = "ACK|FAIL"
	ExpectedACKWait = "ACK|WAIT"
)

// MaxPayloadSize es el tamaño máximo de payload en bytes.
// Es configurable desde config.yaml (protocol.maxPayloadSize).
// Default: 8192 (8KB)
var MaxPayloadSize = 8192

// SetMaxPayloadSize permite configurar el tamaño máximo de payload.
func SetMaxPayloadSize(size int) {
	if size > 0 {
		MaxPayloadSize = size
	}
}

// WriteFrame escribe un frame en conexión con el formato:
// 2 bytes size (uint16 big-endian)][payload]
// Maneja posibles short-writes iterando hasta que se escriban todos los bytes.
func WriteFrame(conn io.Writer, payload []byte) error {
	// Valida que el tamaño del payload no exceda 8192 bytes
	if len(payload) > MaxPayloadSize {
		return fmt.Errorf("payload too large: %d bytes (max: %d)", len(payload), MaxPayloadSize)
	}

	// Crea el frame: [2 bytes header][payload]
	frame := make([]byte, 2+len(payload))

	// Escribe el tamaño en formato big-endian
	binary.BigEndian.PutUint16(frame[0:2], uint16(len(payload)))

	// Copia el payload
	copy(frame[2:], payload)

	// Escribe todo el frame manejando short-writes
	totalWritten := 0
	for totalWritten < len(frame) {
		n, err := conn.Write(frame[totalWritten:])
		if err != nil {
			return err
		}
		totalWritten += n
	}

	return nil
}

// ReadFrame lee un frame completo desde la conexión.
// Maneja posibles lecturas short-reads leyendo exactamente los bytes necesarios.
func ReadFrame(conn io.Reader) ([]byte, error) {
	// Lee el header de tamaño (2 bytes)
	sizeBuf := make([]byte, 2)
	totalRead := 0
	for totalRead < 2 {
		n, err := conn.Read(sizeBuf[totalRead:])
		if err != nil {
			return nil, fmt.Errorf("error reading frame size: %w", err)
		}
		totalRead += n
	}

	// Parsea el tamaño desde big-endian
	size := binary.BigEndian.Uint16(sizeBuf)

	// Lee el payload
	payload := make([]byte, size)
	totalRead = 0
	for totalRead < int(size) {
		n, err := conn.Read(payload[totalRead:])
		if err != nil {
			return nil, fmt.Errorf("error reading frame payload: %w", err)
		}
		totalRead += n
	}

	return payload, nil
}
