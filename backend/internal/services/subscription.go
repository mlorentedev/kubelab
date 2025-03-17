package services

import (
	"github.com/mlorentedev/mlorente-backend/internal/constants"
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// ProcessSubscription processes a complete subscription (verification, creation, tagging)
func ProcessSubscription(email, utmSource string, tags []string) (*models.SubscriptionResult, error) {
	logger.LogFunction("info", constants.Messages.Backend.Info["RequestProcessing"], map[string]string{
		"email":     email,
		"utmSource": utmSource,
	})

	// Check if subscriber already exists
	subscriberCheck, err := CheckSubscriber(email)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["CheckSubscriberError"], err.Error())
		return nil, err
	}

	if subscriberCheck.Success && subscriberCheck.Subscriber != nil {
		// Update tags for existing subscriber
		for _, tag := range tags {
			success := AddTagToSubscriber(subscriberCheck.Subscriber.ID, tag)
			if !success {
				logger.LogFunction("error", constants.Messages.Backend.Error["AddTagError"], map[string]string{
					"email":        email,
					"subscriberId": subscriberCheck.Subscriber.ID,
					"tag":          tag,
				})
				return &models.SubscriptionResult{
					Success: false,
					Message: constants.Messages.Service.Subscription["TagsError"],
				}, nil
			}
		}

		logger.LogFunction("info", constants.Messages.Backend.Info["SubscriberExists"], map[string]string{
			"email": email,
			"id":    subscriberCheck.Subscriber.ID,
		})

		return &models.SubscriptionResult{
			Success:           true,
			Message:           constants.Messages.Service.Subscription["Updated"],
			SubscriberID:      subscriberCheck.Subscriber.ID,
			AlreadySubscribed: true,
		}, nil
	}

	// Create a new subscriber
	newSubscription, err := SubscribeUser(email, utmSource)
	if err != nil {
		logger.LogFunction("error", constants.Messages.Backend.Error["CreateSubscriberError"], err.Error())
		return nil, err
	}

	if newSubscription.Success && newSubscription.Subscriber != nil {
		// Add tags to the new subscriber
		allTags := append([]string{string(models.SubscriptionTagNewSubscriber)}, tags...)

		for _, tag := range allTags {
			success := AddTagToSubscriber(newSubscription.Subscriber.ID, tag)
			if !success {
				logger.LogFunction("error", constants.Messages.Backend.Error["AddTagError"], map[string]string{
					"email":        email,
					"subscriberId": newSubscription.Subscriber.ID,
					"tag":          tag,
				})
				return &models.SubscriptionResult{
					Success: false,
					Message: constants.Messages.Service.Subscription["TagsError"],
				}, nil
			}
		}

		logger.LogFunction("info", constants.Messages.Backend.Info["NewSubscriber"], map[string]string{
			"email": email,
			"id":    newSubscription.Subscriber.ID,
		})

		return &models.SubscriptionResult{
			Success:      true,
			Message:      constants.Messages.Service.Subscription["New"],
			SubscriberID: newSubscription.Subscriber.ID,
		}, nil
	}

	logger.LogFunction("error", constants.Messages.Backend.Error["SubscriptionError"], map[string]string{
		"email":     email,
		"utmSource": utmSource,
	})

	return &models.SubscriptionResult{
		Success: false,
		Message: constants.Messages.Service.Subscription["Error"],
	}, nil
}
