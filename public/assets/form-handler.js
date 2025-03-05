function setupFormHandling(formId, endpoint, redirectUrl = '/success') {
  const form = document.getElementById(formId);
  const statusMessage = form.querySelector('.status-message');
  const emailInput = form.querySelector('input[name="email"]');
  const privacyPolicyCheckbox = form.querySelector('input[name="privacy-policy"]');
  const submitButton = form.querySelector('button[type="submit"]');

  const originalButtonText = submitButton.textContent;

  const tag = form.dataset.tag;
  const utmSource = form.dataset.utmSource;
  const resourceId = form.dataset.resourceId;
  const tags = form.dataset.tags ? form.dataset.tags.split(',') : [];

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    if (!privacyPolicyCheckbox.checked) {
      showStatus(statusMessage, 'Debes aceptar la política de privacidad', 'error');
      return;
    }

    const payload = {
      email: emailInput.value,
      tag,
      utmSource,
    };

    if (resourceId) {
      payload.resourceId = resourceId;
      payload.tags = tags;
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
        window.location.href = redirectUrl;
      } else {
        showStatus(statusMessage, result.message || 'Hubo un error', 'error');
      }
    } catch (error) {
      showStatus(statusMessage, 'Error de conexión', 'error');
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
  statusElement.classList.remove('hidden', 'text-white', 'text-red-500');

  if (type === 'error') {
    statusElement.classList.add('text-red-500');
  } else {
    statusElement.classList.add('text-white');
  }
}

function setButtonState(button, isLoading, text) {
  button.disabled = isLoading;
  button.textContent = text;
}

export default setupFormHandling;
