package common

import (
	"fmt"
	"strings"
)

const (
	batchMsgType    = "BATCH"
	batchHeaderSize = 6 // "BATCH\n"
)

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
