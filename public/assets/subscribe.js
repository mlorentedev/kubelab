
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('subscribe-form');
  const statusMessage = document.getElementById('status-message');
  const emailField = document.querySelector('[name="email"]');
  const privacyPolicyCheckbox = document.getElementById('privacy-policy');
  const tag = form.getAttribute('data-tag');
  const utm_source = form.getAttribute('utm-source');  

  statusMessage.textContent = '';

  if (!emailField) {
    console.error('Email field not found!');
    return;
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!privacyPolicyCheckbox.checked) {
      statusMessage.textContent = 'Debes aceptar la política de privacidad para continuar.';
      return;
    }
    const email = emailField.value;
    const response = await fetch('/api/subscribe', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, tag, utm_source }),
    });

    const result = await response.json();
    statusMessage.textContent = result.message;
    if (response.ok) {
      if (result.already_subscribed) {
        console.log('El usuario ya está suscrito.');
        window.location.href = '/resource-success';
      } else {
        console.log('Subscription successful:', result);
        window.location.href = '/subscription-success';
      }
    } else {
      console.error('Subscription failed:', result);
      statusMessage.textContent = 'Hubo un error al intentar suscribirte. Por favor, inténtalo de nuevo.';
    }
  });
});
