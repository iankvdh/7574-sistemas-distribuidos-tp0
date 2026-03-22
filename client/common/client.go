package common

import (
	"fmt"
	"net"
	"os"
	"os/signal"
	"syscall"

	"github.com/7574-sistemas-distribuidos/docker-compose-init/client/protocol"
	"github.com/op/go-logging"
)

var log = logging.MustGetLogger("log")

// ClientConfig Configuration used by the client
type ClientConfig struct {
	ID            string
	ServerAddress string
}

// Client Entity that encapsulates how
type Client struct {
	config ClientConfig
	conn   net.Conn
	bet    Bet
}

// NewClient Initializes a new client receiving the configuration
// as a parameter
func NewClient(config ClientConfig, bet Bet) *Client {
	client := &Client{
		config: config,
		bet:    bet,
	}
	return client
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

func (c *Client) sendBet() error {
	message := c.bet.buildBetMessage()
	err := protocol.WriteFrame(c.conn, []byte(message))
	if err != nil {
		return err
	}
	return nil
}

// StartClientLoop Send messages to the client until some time threshold is met
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

	// Create the connection the server in every loop iteration. Send an
	err := c.createClientSocket()

	if err != nil {
		log.Criticalf(
			"action: connect | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return // termina gracefull
	}

	// Enviar apuesta
	err = c.sendBet()
	if err != nil {
		log.Errorf(
			"action: send_bet | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		c.conn.Close()
		return
	}

	// Leer y validar ACK del servidor
	ackPayload, err := protocol.ReadFrame(c.conn)
	c.conn.Close()

	if err != nil {
		log.Errorf(
			"action: receive_message | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return
	}

	if string(ackPayload) != protocol.ExpectedACK {
		log.Errorf(
			"action: receive_message | result: fail | client_id: %v | error: %v",
			c.config.ID,
			fmt.Errorf("invalid ACK payload: %q", string(ackPayload)),
		)
		return
	}

	// log de enunciado:
	log.Infof(
		"action: apuesta_enviada | result: success | dni: %s | numero: %s",
		c.bet.Document,
		c.bet.Number,
	)
}
