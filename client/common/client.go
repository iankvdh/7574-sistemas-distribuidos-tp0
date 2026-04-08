package common

import (
	"encoding/csv"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"

	"github.com/7574-sistemas-distribuidos/docker-compose-init/client/protocol"
	"github.com/op/go-logging"
)

var log = logging.MustGetLogger("log")

// ClientConfig Configuration used by the client
type ClientConfig struct {
	ID             string
	ServerAddress  string
	BatchMaxAmount int
}

// Client Entity that encapsulates how
type Client struct {
	config     ClientConfig
	conn       net.Conn
	agencyFile string
}

// NewClient Initializes a new client receiving the configuration
// as a parameter
func NewClient(config ClientConfig, agencyFile string) *Client {
	return &Client{
		config:     config,
		agencyFile: agencyFile,
	}
}

// CreateClientSocket Initializes client socket. In case of
// failure, error returned
func (c *Client) createClientSocket() error {
	conn, err := net.Dial("tcp", c.config.ServerAddress)
	if err != nil {
		return err
	}
	c.conn = conn
	return nil
}

func (c *Client) sendBatch(bets []Bet) error {
	message, err := BuildBatchMessage(bets)
	if err != nil {
		return err
	}

	err = protocol.WriteFrame(c.conn, []byte(message))
	if err != nil {
		return err
	}

	ackPayload, err := protocol.ReadFrame(c.conn)
	if err != nil {
		return err
	}

	ack := string(ackPayload)
	if ack == protocol.ExpectedNACK {
		return fmt.Errorf("server returned fail ACK for batch")
	}

	if ack != protocol.ExpectedACK {
		return fmt.Errorf("invalid ACK payload")
	}

	log.Infof(
		"action: batch_enviado | result: success | cantidad: %s | client_id: %s",
		strconv.Itoa(len(bets)),
		c.config.ID,
	)

	return nil
}

func (c *Client) notifyFinished() error {
	message := EndMsgType + "|" + c.config.ID
	err := protocol.WriteFrame(c.conn, []byte(message))
	if err != nil {
		return err
	}

	resp, err := protocol.ReadFrame(c.conn)
	if err != nil {
		return err
	}

	if string(resp) != protocol.ExpectedACK {
		return fmt.Errorf("invalid END response")
	}

	return nil
}

func (c *Client) queryWinners(stop <-chan struct{}) (int, error) {
	select {
	case <-stop:
		return 0, fmt.Errorf("client stopped")
	default:
	}

	message := QueryMsgType + "|" + c.config.ID
	err := protocol.WriteFrame(c.conn, []byte(message))
	if err != nil {
		return 0, err
	}

	resp, err := protocol.ReadFrame(c.conn)
	if err != nil {
		return 0, err
	}

	respStr := string(resp)
	if !strings.HasPrefix(respStr, WinnersMsgType+"|") {
		return 0, fmt.Errorf("invalid QUERY response")
	}

	parts := strings.SplitN(respStr, "|", 3)
	if len(parts) < 2 {
		return 0, fmt.Errorf("invalid winners payload")
	}

	count, err := strconv.Atoi(parts[1])
	if err != nil {
		return 0, err
	}

	return count, nil
}

// sendBatches lee el CSV de apuestas de forma streaming (línea por línea) y
// las envía en batches al servidor usando stop-and-wait.
// bloqueamos esperando el ACK de cada batch antes de leer el siguiente,
func (c *Client) sendBatches(stop <-chan struct{}) error {
	file, err := os.Open(c.agencyFile)
	if err != nil {
		return err
	}
	defer file.Close()

	reader := csv.NewReader(file)
	currentBatch := make([]Bet, 0, c.config.BatchMaxAmount)
	currentBytes := batchHeaderSize

	for {
		select {
		case <-stop:
			return fmt.Errorf("client stopped")
		default:
		}

		row, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		if len(row) != 5 {
			return fmt.Errorf("invalid CSV row with %d columns", len(row))
		}

		bet := Bet{
			Agency:    c.config.ID,
			FirstName: row[0],
			LastName:  row[1],
			Document:  row[2],
			Birthdate: row[3],
			Number:    row[4],
		}

		betSize := len(bet.ToRow()) + 1 // +1 para el \n

		// Chequeamos que una apuesta individual (más encabezado) no exceda el MaxPayloadSize
		if batchHeaderSize+betSize > protocol.MaxPayloadSize {
			return fmt.Errorf("single bet message size (%d bytes) exceeds limit of %d bytes", batchHeaderSize+betSize, protocol.MaxPayloadSize)
		}

		wouldExceedSize := currentBytes+betSize > protocol.MaxPayloadSize
		wouldExceedCount := len(currentBatch)+1 > c.config.BatchMaxAmount

		if wouldExceedSize || wouldExceedCount {
			if len(currentBatch) > 0 {
				if err := c.sendBatch(currentBatch); err != nil {
					return err
				}
			}
			// Reiniciamos el batch para la próxima tanda
			currentBatch = currentBatch[:0]
			currentBytes = batchHeaderSize
		}

		// Agregar la apuesta al batch
		currentBatch = append(currentBatch, bet)
		currentBytes += betSize
	}

	// Envía el último batch si no está vacío
	if len(currentBatch) > 0 {
		if err := c.sendBatch(currentBatch); err != nil {
			return err
		}
	}

	return nil
}

// StartClient se conecta al server y hace todo esto por la misma conexión persistente:
// sendBatches -> notifyFinished -> queryWinners
func (c *Client) StartClient() {
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGTERM)

	stop := make(chan struct{})

	// thread para escuchar signals y cerrar la conexión si es necesario
	go func() {
		<-sigs
		log.Infof("action: shutdown | result: in_progress | client_id: %v", c.config.ID)
		if c.conn != nil {
			c.conn.Close()
			log.Infof("action: close_connection | result: success | client_id: %v", c.config.ID)
		}
		close(stop) // Notifica al loop principal
	}()

	// Chequea si llegó señal antes de conectar
	select {
	case <-stop:
		log.Infof("action: loop_terminated | result: success | client_id: %v", c.config.ID)
		return
	default:
	}

	// Crea una conexión persistente
	err := c.createClientSocket()
	if err != nil {
		log.Errorf(
			"action: connect | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return
	}
	defer c.conn.Close()

	// Manda todos los batches
	err = c.sendBatches(stop)
	if err != nil {
		log.Errorf(
			"action: send_batch | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return
	}

	log.Infof("action: batches_enviados | result: success | client_id: %v", c.config.ID)

	// Notifica que ya mandó todos los batches
	err = c.notifyFinished()
	if err != nil {
		log.Errorf(
			"action: fin_envio | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return
	}
	log.Infof("action: fin_envio | result: success | client_id: %v", c.config.ID)

	count, err := c.queryWinners(stop)
	if err != nil {
		log.Errorf(
			"action: consulta_ganadores | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return
	}

	log.Infof("action: consulta_ganadores | result: success | cant_ganadores: %d", count)
}
