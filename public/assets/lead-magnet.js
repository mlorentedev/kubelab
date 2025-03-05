import setupFormHandling from './form-handler.js';

document.addEventListener('DOMContentLoaded', () => {
  const leadMagnetForm = document.getElementById('lead-magnet-form');

  if (leadMagnetForm) {
    setupFormHandling('lead-magnet-form', '/api/lead-magnet', '/resource-success');
  }
});
