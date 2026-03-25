package common

import (
	"fmt"
	"net"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

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

func (c *Client) sendControlMessage(message string) (string, error) {
	err := c.createClientSocket()
	if err != nil {
		return "", err
	}

	err = protocol.WriteFrame(c.conn, []byte(message))
	if err != nil {
		c.conn.Close()
		return "", err
	}

	payload, err := protocol.ReadFrame(c.conn)
	c.conn.Close()
	if err != nil {
		return "", err
	}

	return string(payload), nil
}

func (c *Client) notifyFinished() error {
	resp, err := c.sendControlMessage(EndMsgType + "|" + c.config.ID)
	if err != nil {
		return err
	}
	if resp != protocol.ExpectedACK {
		return fmt.Errorf("invalid END response")
	}
	return nil
}

func (c *Client) queryWinners(stop <-chan struct{}) (int, error) {
	for {
		select {
		case <-stop:
			return 0, fmt.Errorf("client stopped")
		default:
		}

		resp, err := c.sendControlMessage(QueryMsgType + "|" + c.config.ID)
		if err != nil {
			return 0, err
		}

		if resp == protocol.ExpectedACKWait {
			time.Sleep(200 * time.Millisecond)
			continue
		}

		if !strings.HasPrefix(resp, WinnersMsgType+"|") {
			return 0, fmt.Errorf("invalid QUERY response")
		}

		parts := strings.SplitN(resp, "|", 3)
		if len(parts) < 2 {
			return 0, fmt.Errorf("invalid winners payload")
		}

		count, err := strconv.Atoi(parts[1])
		if err != nil {
			return 0, err
		}

		return count, nil
	}
}

func (c *Client) sendBatches(stop <-chan struct{}) error {
	i := 0
	for i < len(c.bets) {
		select {
		case <-stop:
			return fmt.Errorf("client stopped")
		default:
		}

		// Vemos cuántas apuestas caben en este envío (Batch Dinámico)
		currentBatch, nextIndex, err := c.determineNextBatch(i)
		if err != nil {
			return err
		}

		err = c.createClientSocket()
		if err != nil {
			return err
		}

		err = c.sendBatch(currentBatch)
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
			return fmt.Errorf("server returned fail ACK for batch starting at %d", i)
		}
		if ack != protocol.ExpectedACK {
			return fmt.Errorf("invalid ACK payload")
		}

		log.Infof(
			"action: batch_enviado | result: success | cantidad: %d | client_id: %s",
			len(currentBatch),
			c.config.ID,
		)
		i = nextIndex
	}

	return nil
}

func (c *Client) determineNextBatch(startIndex int) ([]Bet, int, error) {
	var batch []Bet
	currentBytes := batchHeaderSize

	for j := startIndex; j < len(c.bets); j++ {
		bet := c.bets[j]
		betSize := len(bet.ToRow()) + 1

		if batchHeaderSize+betSize > protocol.MaxPayloadSize {
			if len(batch) == 0 {
				return nil, 0, fmt.Errorf("bet at index %d is too large (%d bytes) for protocol limit", j, batchHeaderSize+betSize)
			}
			break
		}

		if currentBytes+betSize > protocol.MaxPayloadSize || len(batch)+1 > c.config.BatchMaxAmount {
			break
		}

		batch = append(batch, bet)
		currentBytes += betSize
	}

	return batch, startIndex + len(batch), nil
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

	err = c.notifyFinished()
	if err != nil {
		log.Errorf(
			"action: fin_envio | result: fail | client_id: %v | error: %v",
			c.config.ID,
			err,
		)
		return
	}

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
