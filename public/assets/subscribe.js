
document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('subscribe-form');
  const statusMessage = document.getElementById('status-message');
  const emailField = document.querySelector('[name="email"]');
  const privacyPolicyCheckbox = document.getElementById('privacy-policy');

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
      body: JSON.stringify({ email }),
    });

    const result = await response.json();
    statusMessage.textContent = result.message;
    if (response.ok) {
      console.log('Subscription successful:', result);
      window.location.href = '/subscription';
    }
  });
});
