document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('subscribe-form');
  const statusMessage = document.getElementById('status-message');
  const emailField = document.querySelector('[name="email"]');
  const privacyPolicyCheckbox = document.getElementById('privacy-policy');
  const tag = form.getAttribute('data-tag');
  const utmSource = form.getAttribute('utm-source');  
  const autId = form.getAttribute('aut-id');

  statusMessage.textContent = '';

  if (!emailField) {
    console.error('Email field not found in the form.');
    return;
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!privacyPolicyCheckbox.checked) {
      statusMessage.textContent = 'Debes aceptar la política de privacidad para continuar.';
      return;
    }
    const email = emailField.value;
    const response = await fetch('/api/newsletter', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email, tag, utmSource, autId }),
    });

    const result = await response.json();
    statusMessage.textContent = result.message;
    if (response.ok) {
      if (result.already_subscribed) {
        console.warn('User already subscribed:', email);
        window.location.href = '/resource-success';
      } else {
        console.info('User subscribed successfully:', email);
        window.location.href = '/subscription-success';
      }
    } else {
      console.error('Error subscribing user:', email, result.error);
      statusMessage.textContent = 'Hubo un error al intentar suscribirte. Por favor, inténtalo de nuevo.';
    }
  });
});
