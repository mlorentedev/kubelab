import setupFormHandling from './formHandler.js';

document.addEventListener('DOMContentLoaded', () => {
  const leadMagnetForm = document.getElementById('lead-magnet-form');

  if (leadMagnetForm) {
    setupFormHandling('lead-magnet-form', '/api/leadMagnet', '/resource-success');
  }
});
