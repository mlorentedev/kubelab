package services

import (
	"github.com/mlorentedev/mlorente-backend/internal/models"
	"github.com/mlorentedev/mlorente-backend/pkg/logger"
)

// Mensajes para resultados de suscripción
const (
	MsgSubscriptionUpdated = "Suscriptor existente actualizado."
	MsgSubscriptionNew     = "Nuevo suscriptor añadido."
	MsgSubscriptionError   = "No se pudo completar la suscripción."
	MsgTagsUpdateError     = "Error al actualizar los tags del suscriptor."
	MsgServerError         = "Error interno del servidor."
)

// ProcessSubscription procesa una suscripción completa (verificación, creación, etiquetado)
func ProcessSubscription(email, utmSource string, tags []string) (*models.SubscriptionResult, error) {
	logger.LogFunction("info", "Processing subscription request", map[string]string{
		"email":     email,
		"utmSource": utmSource,
	})

	// Verificar si el suscriptor ya existe
	subscriberCheck, err := CheckSubscriber(email)
	if err != nil {
		return nil, err
	}

	if subscriberCheck.Success && subscriberCheck.Subscriber != nil {
		// Actualizar tags para un suscriptor existente
		for _, tag := range tags {
			success := AddTagToSubscriber(subscriberCheck.Subscriber.ID, tag)
			if !success {
				return &models.SubscriptionResult{
					Success: false,
					Message: MsgTagsUpdateError,
				}, nil
			}
		}

		return &models.SubscriptionResult{
			Success:           true,
			Message:           MsgSubscriptionUpdated,
			SubscriberID:      subscriberCheck.Subscriber.ID,
			AlreadySubscribed: true,
		}, nil
	}

	// Crear un nuevo suscriptor
	newSubscription, err := SubscribeUser(email, utmSource)
	if err != nil {
		return nil, err
	}

	if newSubscription.Success && newSubscription.Subscriber != nil {
		// Añadir etiquetas al nuevo suscriptor
		allTags := append([]string{string(models.SubscriptionTagNewSubscriber)}, tags...)

		for _, tag := range allTags {
			success := AddTagToSubscriber(newSubscription.Subscriber.ID, tag)
			if !success {
				return &models.SubscriptionResult{
					Success: false,
					Message: MsgTagsUpdateError,
				}, nil
			}
		}

		return &models.SubscriptionResult{
			Success:      true,
			Message:      MsgSubscriptionNew,
			SubscriberID: newSubscription.Subscriber.ID,
		}, nil
	}

	return &models.SubscriptionResult{
		Success: false,
		Message: MsgSubscriptionError,
	}, nil
}
