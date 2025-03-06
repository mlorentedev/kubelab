function setupFormHandling(formId, endpoint, redirectUrl = '/success') {
  const form = document.getElementById(formId);
  const statusMessage = document.getElementById('status-message');
  const emailInput = form.querySelector('input[name="email"]');
  const privacyPolicyCheckbox = form.querySelector('input[name="privacy-policy"]');
  const submitButton = form.querySelector('button[type="submit"]');

  const originalButtonText = submitButton.textContent;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!privacyPolicyCheckbox.checked) {
      showStatus(statusMessage, 'Debes aceptar la política de privacidad', 'error');
      return;
    }

    const payload = {};

    if (formId === 'subscribe-form') {
      payload.email = emailInput.value;
      payload.utmSource = form.dataset.utmSource;
      payload.tag = form.dataset.tag;
    } else {
      payload.email = emailInput.value;
      payload.utmSource = form.dataset.utmSource;
      payload.fileId = form.dataset.fileId;
      payload.resourceId = form.dataset.resourceId;
      payload.tags = form.dataset.tags ? form.dataset.tags.split(',') : [];
    }

    try {
      setButtonState(submitButton, true, 'Procesando...');
      emailInput.disabled = true;
      privacyPolicyCheckbox.disabled = true;

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      const result = await response.json();

      if (response.ok) {
        if (result.alreadySubscribed && formId === 'subscribe-form') {
          showStatus(
            statusMessage,
            'Ya estabas suscrito, mándame un correo si no estás recibiendo los mails ;)',
            'error'
          );
          return;
        }
        window.location.href = redirectUrl;
      } else {
        showStatus(statusMessage, result.message || 'Hubo un error', 'error');
      }
    } catch (error) {
      showStatus(statusMessage, 'Error de conexión', error);
    } finally {
      setButtonState(submitButton, false, originalButtonText);
      emailInput.disabled = false;
      privacyPolicyCheckbox.disabled = false;
    }
  });
}

function showStatus(statusElement, message, type = 'info') {
  if (!statusElement) {
    return;
  }

  statusElement.textContent = message;
  statusElement.classList.remove('hidden', 'text-white', 'text-white-500');

  if (type === 'error') {
    statusElement.classList.add('text-white-500');
  } else {
    statusElement.classList.add('text-white');
  }
}

function setButtonState(button, isLoading, text) {
  button.disabled = isLoading;
  button.textContent = text;
}

export default setupFormHandling;
