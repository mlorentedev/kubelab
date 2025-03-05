import { checkSubscriber, subscribeUser, addTagToSubscriber } from './beehiiv.service';
import { type SubscriptionResult, SubscriptionSource, SubscriptionTag } from './types';

import { logFunction } from './utils';

export async function processSubscription(
  email: string,
  tags: string[] = [],
  utmSource: SubscriptionSource = SubscriptionSource.LandingPage
): Promise<SubscriptionResult> {
  try {
    const subscriberCheck = await checkSubscriber(email);

    if (subscriberCheck.success && subscriberCheck.subscriber) {
      const tagResults = await Promise.all(
        tags.map((tag) => addTagToSubscriber(subscriberCheck.subscriber!.id, tag))
      );

      return {
        success: true,
        message: 'Suscriptor existente actualizado',
        subscriberId: subscriberCheck.subscriber.id,
        alreadySubscribed: true,
      };
    }

    const newSubscription = await subscribeUser(email, utmSource);

    if (newSubscription.success && newSubscription.subscriber) {
      await addTagToSubscriber(newSubscription.subscriber.id, SubscriptionTag.NewSubscriber);

      const additionalTagResults = await Promise.all(
        tags.map((tag) => addTagToSubscriber(newSubscription.subscriber!.id, tag))
      );

      return {
        success: true,
        message: 'Nuevo suscriptor añadido',
        subscriberId: newSubscription.subscriber.id,
      };
    }

    return {
      success: false,
      message: 'No se pudo completar la suscripción',
    };
  } catch (error) {
    logFunction('error', 'Error en procesamiento de suscripción', error);
    return {
      success: false,
      message: 'Error interno del servidor',
    };
  }
}
