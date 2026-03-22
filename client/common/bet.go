package common

import "fmt"

const (
	QueryMsgType   = "QUERY"
	EndMsgType     = "END"
	WinnersMsgType = "WINNERS"
)

// Bet representa una apuesta de lotería enviada por una agencia.
type Bet struct {
	Agency    string
	FirstName string
	LastName  string
	Document  string
	Birthdate string
	Number    string
}

// ToRow serializa una apuesta en una fila para enviarla dentro de un batch.
// Formato: agency|first_name|last_name|document|birthdate|number
func (b Bet) ToRow() string {
	return fmt.Sprintf(
		"%s|%s|%s|%s|%s|%s",
		b.Agency,
		b.FirstName,
		b.LastName,
		b.Document,
		b.Birthdate,
		b.Number,
	)
}
