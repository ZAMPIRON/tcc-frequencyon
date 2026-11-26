import './commands';

// O teste nunca usa a câmera de verdade: as telas do totem abrem sem câmera e as imagens
// são enviadas pelo próprio teste (cy.enviarFrames). Assim uma webcam ligada no computador
// não interfere no resultado.
Cypress.on('window:before:load', (win) => {
  if (win.navigator.mediaDevices) {
    win.navigator.mediaDevices.getUserMedia = () => Promise.reject(new win.DOMException('Câmera desligada nos testes', 'NotAllowedError'));
  }
});
