package services

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"

	"github.com/mlorentedev/mlorente-backend/internal/constants"
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

// CheckSubscriber verifies if a subscriber exists by email
func CheckSubscriber(email string) (*struct {
	Success    bool
	Subscriber *models.Subscriber
}, error) {
	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions/by_email/%s",
		conf.Beehiiv.PubID, email)

	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestCreationError"], err.Error())
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestExecutionError"], err.Error())
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["ResponseReadError"], err.Error())
		return nil, err
	}

	var result struct {
		Data *models.Subscriber `json:"data"`
	}

	if err := json.Unmarshal(body, &result); err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["UnmarshalError"], err.Error())
		return nil, err
	}

	if result.Data == nil || result.Data.ID == "" {
		logger.LogFunction("info", constants.Messages.Backend.Info["SubscriberNotFound"], email)
		return &struct {
			Success    bool
			Subscriber *models.Subscriber
		}{
			Success: false,
		}, nil
	}

	logger.LogFunction("info", constants.Messages.Backend.Info["SubscriberExists"], email)
	return &struct {
		Success    bool
		Subscriber *models.Subscriber
	}{
		Success:    true,
		Subscriber: result.Data,
	}, nil
}

// SubscribeUser creates a new subscriber
func SubscribeUser(email, utmSource string) (*struct {
	Success    bool
	Subscriber *models.Subscriber
}, error) {
	logger.LogFunction("info", constants.Messages.Backend.Info["SubscriptionProcessing"], map[string]string{
		"email":     email,
		"utmSource": utmSource,
	})

	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions", conf.Beehiiv.PubID)

	data := map[string]interface{}{
		"email":               email,
		"utm_source":          utmSource,
		"reactivate_existing": true,
		"send_welcome_email":  true,
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["MarshalError"], err.Error())
		return nil, err
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestCreationError"], err.Error())
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestExecutionError"], err.Error())
		return nil, err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["ResponseReadError"], err.Error())
		return nil, err
	}

	var result struct {
		Data *models.Subscriber `json:"data"`
	}

	if err := json.Unmarshal(body, &result); err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["UnmarshalError"], err.Error())
		return nil, err
	}

	if result.Data == nil || result.Data.ID == "" {
		logger.LogFunction("error", constants.Messages.Backend.Error["CreateSubscriberError"], string(body))
		return &struct {
			Success    bool
			Subscriber *models.Subscriber
		}{
			Success: false,
		}, nil
	}

	logger.LogFunction("info", constants.Messages.Backend.Info["NewSubscriber"], email)
	return &struct {
		Success    bool
		Subscriber *models.Subscriber
	}{
		Success:    true,
		Subscriber: result.Data,
	}, nil
}

// AddTagToSubscriber adds a tag to an existing subscriber
func AddTagToSubscriber(subscriptionID, tag string) bool {
	if tag == "" {
		logger.LogFunction("warn", constants.Messages.Backend.Warn["EmptyTag"], subscriptionID)
		return false
	}

	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions/%s/tags",
		conf.Beehiiv.PubID, subscriptionID)

	data := map[string]interface{}{
		"tags": []string{tag},
	}

	jsonData, err := json.Marshal(data)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["MarshalError"], err.Error())
		return false
	}

	req, err := http.NewRequest("POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestCreationError"], err.Error())
		return false
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestExecutionError"], err.Error())
		return false
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["ResponseReadError"], err.Error())
		return false
	}

	var result struct {
		Data *models.Subscriber `json:"data"`
	}

	if err := json.Unmarshal(body, &result); err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["UnmarshalError"], err.Error())
		return false
	}

	if result.Data == nil || result.Data.ID == "" {
		logger.LogFunction("error", constants.Messages.Backend.Error["AddTagError"], map[string]string{
			"subscriptionId": subscriptionID,
			"tag":            tag,
			"response":       string(body),
		})
		return false
	}

	logger.LogFunction("info", constants.Messages.Backend.Info["TagAdded"], map[string]string{
		"subscriptionId": subscriptionID,
		"tag":            tag,
	})
	return true
}

// UnsubscribeUser unsubscribes a user from the newsletter
func UnsubscribeUser(email string) (*models.SubscriptionResult, error) {
	subscriberCheck, err := CheckSubscriber(email)
	if err != nil {
		return nil, err
	}

	if !subscriberCheck.Success || subscriberCheck.Subscriber == nil {
		logger.LogFunction("warn", constants.Messages.Backend.Info["SubscriberNotFound"], map[string]string{
			"action": "unsubscribe",
			"email":  email,
		})
		return &models.SubscriptionResult{
			Success: false,
			Message: constants.Messages.Frontend.Errors["EmailNotSubscribed"],
		}, nil
	}

	subscriptionID := subscriberCheck.Subscriber.ID
	logger.LogFunction("info", constants.Messages.Backend.Info["UserUnsubscribed"], map[string]string{
		"email": email,
		"id":    subscriptionID,
	})

	url := fmt.Sprintf("https://api.beehiiv.com/v2/publications/%s/subscriptions/%s",
		conf.Beehiiv.PubID, subscriptionID)

	req, err := http.NewRequest("DELETE", url, nil)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestCreationError"], err.Error())
		return nil, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+conf.Beehiiv.APIKey)

	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["RequestExecutionError"], err.Error())
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode == 204 {
		logger.LogFunction("info", constants.Messages.Backend.Info["UserUnsubscribed"], email)
		return &models.SubscriptionResult{
			Success: true,
			Message: constants.Messages.Frontend.Success["Unsubscription"],
		}, nil
	} else {
		body, _ := io.ReadAll(resp.Body)
		logger.LogFunction("error", constants.Messages.Backend.Error["UnsubscribeError"], string(body))
		return &models.SubscriptionResult{
			Success: false,
			Message: constants.Messages.Frontend.Errors["ServerError"],
		}, errors.New("error unsubscribing user")
	}
}
