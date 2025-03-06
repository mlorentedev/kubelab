import setupFormHandling from './formHandler.js';

document.addEventListener('DOMContentLoaded', () => {
  const subscribeForm = document.getElementById('subscribe-form');

  if (subscribeForm) {
    setupFormHandling('subscribe-form', '/api/subscribe', '/subscription-success');
  }
});
