// public/assets/unsubscribe.js

document.addEventListener('DOMContentLoaded', () => {
  const unsubscribeForm = document.getElementById('unsubscribe-form');

  if (unsubscribeForm) {
    unsubscribeForm.addEventListener('submit', async (e) => {
      e.preventDefault();

      const emailInput = unsubscribeForm.querySelector('input[name="email"]');
      const statusMessage = document.getElementById('status-message');
      const submitButton = unsubscribeForm.querySelector('button[type="submit"]');

      if (!emailInput || !statusMessage || !submitButton) {
        console.error('Form elements not found');
        return;
      }

      const email = emailInput.value.trim();

      if (!email) {
        statusMessage.textContent = 'Por favor, introduce tu dirección de correo.';
        statusMessage.classList.add('text-red-500');
        return;
      }

      try {
        submitButton.disabled = true;
        submitButton.textContent = 'Procesando...';
        statusMessage.textContent = '';

        const response = await fetch('/api/unsubscribe', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ email }),
        });

        const result = await response.json();

        if (result.success) {
          window.location.href = '/unsubscribe-success';
        } else {
          statusMessage.textContent =
            result.message || 'Ha ocurrido un error al procesar tu solicitud.';
          statusMessage.classList.add('text-red-500');
          submitButton.disabled = false;
          submitButton.textContent = 'Darme de baja';
        }
      } catch (error) {
        console.error('Error:', error);
        statusMessage.textContent = 'Ha ocurrido un error al procesar tu solicitud.';
        statusMessage.classList.add('text-red-500');
        submitButton.disabled = false;
        submitButton.textContent = 'Darme de baja';
      }
    });
  }
});
