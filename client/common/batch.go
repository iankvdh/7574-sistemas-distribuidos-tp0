package common

import (
	"encoding/csv"
	"fmt"
	"os"
	"strings"
)

const (
	batchMsgType = "BATCH"
)

// LoadBetsFromCSV lee las apuestas de una agencia desde un archivo CSV
// y las mapea a objetos Bet.
// Formato del CSV por fila: first_name,last_name,document,birthdate,number
func LoadBetsFromCSV(filePath string, agency string) ([]Bet, error) {
	file, err := os.Open(filePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := csv.NewReader(file)
	rows, err := reader.ReadAll()
	if err != nil {
		return nil, err
	}

	bets := make([]Bet, 0, len(rows))
	for _, row := range rows {
		if len(row) != 5 {
			return nil, fmt.Errorf("invalid CSV row with %d columns", len(row))
		}

		bets = append(bets, Bet{
			Agency:    agency,
			FirstName: row[0],
			LastName:  row[1],
			Document:  row[2],
			Birthdate: row[3],
			Number:    row[4],
		})
	}

	return bets, nil
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
