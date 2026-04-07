package common

import (
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"strings"
)

const (
	batchMsgType    = "BATCH"
	batchHeaderSize = 6 // "BATCH\n"
)

// BetOrError encapsula una apuesta o un error
type BetOrError struct {
	Bet Bet
	Err error
}

// LoadBetsFromCSVStreaming lee las apuestas de una agencia desde un archivo CSV
// usando streaming (línea por línea) para no cargar todo en memoria.
// Retorna un channel que emite BetOrError.
// El caller debe consumir el channel hasta que se cierre.
func LoadBetsFromCSVStreaming(filePath string, agency string) (<-chan BetOrError, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}

	ch := make(chan BetOrError)

	// lanzo una goroutine para leer el archivo y enviar las bets al channel
	go func() {
		defer file.Close()
		defer close(ch) // al finalizar la goroutine, cerramos el channel y luego el file.

		reader := csv.NewReader(file)

		for {
			row, err := reader.Read()
			if err == io.EOF {
				break
			}
			if err != nil {
				ch <- BetOrError{Err: err}
				return
			}

			if len(row) != 5 {
				ch <- BetOrError{Err: fmt.Errorf("invalid CSV row with %d columns", len(row))}
				return
			}

			ch <- BetOrError{
				Bet: Bet{
					Agency:    agency,
					FirstName: row[0],
					LastName:  row[1],
					Document:  row[2],
					Birthdate: row[3],
					Number:    row[4],
				},
			}
		}
	}()

	return ch, nil
}

// BuildBatchMessage serializa múltiples apuestas en un solo mensaje batch.
// Formato del mensaje:
// BATCH\n
// agency|first_name|last_name|document|birthdate|number\n
func BuildBatchMessage(bets []Bet) (string, error) {
	if len(bets) == 0 {
		return "", fmt.Errorf("cannot build empty batch")
	}

	var builder strings.Builder
	builder.WriteString(batchMsgType)
	builder.WriteString("\n")

	for _, bet := range bets {
		builder.WriteString(bet.ToRow())
		builder.WriteString("\n")
	}

	return builder.String(), nil
}
