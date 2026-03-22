package common

import "fmt"

// Bet representa una apuesta de lotería enviada por una agencia.
type Bet struct {
	Agency    string
	FirstName string
	LastName  string
	Document  string
	Birthdate string
	Number    string
}

// buildBetMessage serializa el contenido de la apuesta para su transporte.
// Formato: BET|agencia|nombre|apellido|documento|nacimiento|numero
func (b Bet) buildBetMessage() string {
	return fmt.Sprintf(
		"BET|%s|%s|%s|%s|%s|%s",
		b.Agency,
		b.FirstName,
		b.LastName,
		b.Document,
		b.Birthdate,
		b.Number,
	)
}
