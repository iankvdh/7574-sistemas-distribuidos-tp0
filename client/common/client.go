package common

import (
	"fmt"
	"net"
	"os"
	"os/signal"
	"strconv"
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
	config ClientConfig
	conn   net.Conn
	bets   []Bet
}

// NewClient Initializes a new client receiving the configuration
// as a parameter
func NewClient(config ClientConfig, bets []Bet) *Client {
	client := &Client{
		config: config,
		bets:   bets,
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

func (c *Client) sendBatch(bets []Bet) error {
	message, err := BuildBatchMessage(bets)
	if err != nil {
		return err
	}

	err = protocol.WriteFrame(c.conn, []byte(message))
	if err != nil {
		return err
	}
	return nil
}

func (c *Client) sendBatches(stop <-chan struct{}) error {
	for i := 0; i < len(c.bets); i += c.config.BatchMaxAmount {
		select {
		case <-stop:
			return fmt.Errorf("client stopped")
		default:
		}

		end := i + c.config.BatchMaxAmount
		if end > len(c.bets) {
			end = len(c.bets)
		}

		err := c.createClientSocket()
		if err != nil {
			return err
		}

		batch := c.bets[i:end]
		err = c.sendBatch(batch)
		if err != nil {
			c.conn.Close()
			return err
		}

		ackPayload, err := protocol.ReadFrame(c.conn)
		c.conn.Close()
		if err != nil {
			return err
		}

		ack := string(ackPayload)
		if ack == protocol.ExpectedNACK {
			return fmt.Errorf("server returned fail ACK for batch size %d", len(batch))
		}

		if ack != protocol.ExpectedACK {
			return fmt.Errorf("invalid ACK payload")
		}

		log.Infof(
			"action: batch_enviado | result: success | cantidad: %s | client_id: %s",
			strconv.Itoa(len(batch)),
			c.config.ID,
		)
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

	err := c.sendBatches(stop)
	if err != nil {
		log.Errorf(
			"action: send_batch | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return
	}

	log.Infof("action: batches_enviados | result: success | client_id: %v", c.config.ID)
}
