package services

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/ioutil"
	"net/http"

	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/pkg/config"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

var conf *config.Config

func init() {
	var err error
	if conf == nil {
		conf, err = config.GetConfig()
		if err != nil {
			panic(err)
		}
	}
}

// CheckSubscriber verifica si un suscriptor existe por email
func CheckSubscriber(email string) (*struct {
	Success    bool
	Subscriber *models.Subscriber
}, error) {
	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions/by_email/%s",
		conf.Beehiiv.PubID, email)

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		logger.LogFunction("error", "Error creating request to check subscriber", err.Error())
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", "Error sending request to check subscriber", err.Error())
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		logger.LogFunction("error", "Error reading response body", err.Error())
		return nil, err
	}

	var result struct {
		Data *models.Subscriber `json:"data"`
	}

	if err := json.Unmarshal(body, &result); err != nil {
		logger.LogFunction("error", "Error unmarshaling response", err.Error())
		return nil, err
	}

	if result.Data == nil || result.Data.ID == "" {
		logger.LogFunction("info", "Subscriber not found", email)
		return &struct {
			Success    bool
			Subscriber *models.Subscriber
		}{
			Success: false,
		}, nil
	}

	logger.LogFunction("info", "Subscriber exists", email)
	return &struct {
		Success    bool
		Subscriber *models.Subscriber
	}{
		Success:    true,
		Subscriber: result.Data,
	}, nil
}

// SubscribeUser crea un nuevo suscriptor
func SubscribeUser(email, utmSource string) (*struct {
	Success    bool
	Subscriber *models.Subscriber
}, error) {
	logger.LogFunction("info", fmt.Sprintf("Subscribing user with utm_source: %s", utmSource), email)

	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions", conf.Beehiiv.PubID)

	data := map[string]interface{}{
		"email":               email,
		"utm_source":          utmSource,
		"reactivate_existing": true,
		"send_welcome_email":  true,
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		logger.LogFunction("error", "Error marshaling subscription data", err.Error())
		return nil, err
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		logger.LogFunction("error", "Error creating request to subscribe user", err.Error())
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", "Error sending request to subscribe user", err.Error())
		return nil, err
	}
	defer resp.Body.Close()

	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		logger.LogFunction("error", "Error reading response body", err.Error())
		return nil, err
	}

	var result struct {
		Data *models.Subscriber `json:"data"`
	}

	if err := json.Unmarshal(body, &result); err != nil {
		logger.LogFunction("error", "Error unmarshaling response", err.Error())
		return nil, err
	}

	if result.Data == nil || result.Data.ID == "" {
		logger.LogFunction("error", "Error subscribing user, API response", string(body))
		return &struct {
			Success    bool
			Subscriber *models.Subscriber
		}{
			Success: false,
		}, nil
	}

	logger.LogFunction("info", "New subscriber created", email)
	return &struct {
		Success    bool
		Subscriber *models.Subscriber
	}{
		Success:    true,
		Subscriber: result.Data,
	}, nil
}

func AddTagToSubscriber(subscriptionID, tag string) bool {
	if tag == "" {
		logger.LogFunction("warn", "Empty tag not added", subscriptionID)
		return false
	}

	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions/%s/tags",
		conf.Beehiiv.PubID, subscriptionID)

	data := map[string]interface{}{
		"tags": []string{tag},
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		logger.LogFunction("error", "Error marshaling tag data", err.Error())
		return false
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		logger.LogFunction("error", "Error creating request to add tag", err.Error())
		return false
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", "Error sending request to add tag", err.Error())
		return false
	}
	defer resp.Body.Close()

	body, err := ioutil.ReadAll(resp.Body)
	if err != nil {
		logger.LogFunction("error", "Error reading response body", err.Error())
		return false
	}

	var result struct {
		Data *models.Subscriber `json:"data"`
	}

	if err := json.Unmarshal(body, &result); err != nil {
		logger.LogFunction("error", "Error unmarshaling response", err.Error())
		return false
	}

	if result.Data == nil || result.Data.ID == "" {
		logger.LogFunction("error", "Error adding tag to subscriber", map[string]string{
			"subscriptionId": subscriptionID,
			"tag":            tag,
			"response":       string(body),
		})
		return false
	}

	logger.LogFunction("info", fmt.Sprintf("Tag added to subscriber: %s", tag), subscriptionID)
	return true
}

// UnsubscribeUser cancela la suscripción de un usuario
func UnsubscribeUser(email string) (*models.SubscriptionResult, error) {
	subscriberCheck, err := CheckSubscriber(email)
	if err != nil {
		return nil, err
	}

	if !subscriberCheck.Success || subscriberCheck.Subscriber == nil {
		logger.LogFunction("warn", "Subscriber not found", map[string]string{
			"action": "unsubscribe",
			"email":  email,
		})
		return &models.SubscriptionResult{
			Success: false,
			Message: "Este email no está suscrito.",
		}, nil
	}

	subscriptionID := subscriberCheck.Subscriber.ID
	logger.LogFunction("info", fmt.Sprintf("Unsubscribing user with id: %s", subscriptionID), email)

	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions/%s",
		conf.Beehiiv.PubID, subscriptionID)

	req, err := http.NewRequest("DELETE", url, nil)
	if err != nil {
		logger.LogFunction("error", "Error creating request to unsubscribe user", err.Error())
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", "Error sending request to unsubscribe user", err.Error())
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode == 204 {
		logger.LogFunction("info", "User unsubscribed successfully", email)
		return &models.SubscriptionResult{
			Success: true,
			Message: "Se ha cancelado tu suscripción correctamente.",
		}, nil
	} else {
		body, _ := ioutil.ReadAll(resp.Body)
		logger.LogFunction("error", "Error unsubscribing user", string(body))
		return &models.SubscriptionResult{
			Success: false,
			Message: "Error interno del servidor.",
		}, errors.New("error unsubscribing user")
	}
}
