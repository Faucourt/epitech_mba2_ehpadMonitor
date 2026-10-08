// Sonde de mesure seulement, a installer dans la page Wokwi avant le lancement
// qui cree les connexions audio. Aucun oscillateur ni son artificiel ajoute.
// Exporter window.tpAudio apres un SOS et le retour au silence.
// Recharger la page pour retirer l'instrumentation. Ne pas installer deux fois.
window.tpAudio = [];
const originalConnect = AudioNode.prototype.connect;
AudioNode.prototype.connect = function (destination, ...args) {
  if (destination instanceof AudioDestinationNode) {
    const analyser = this.context.createAnalyser();
    analyser.fftSize = 2048;
    originalConnect.call(this, analyser);
    originalConnect.call(analyser, destination);
    const buffer = new Float32Array(2048);
    const context = this.context;
    setInterval(() => {
      analyser.getFloatTimeDomainData(buffer);
      const rms = Math.sqrt(buffer.reduce((sum, x) => sum + x * x, 0) / buffer.length);
      window.tpAudio.push({wall: Date.now(), audioTime: context.currentTime, state: context.state, rms});
      if (window.tpAudio.length > 3000) window.tpAudio.shift();
    }, 100);
    return destination;
  }
  return originalConnect.call(this, destination, ...args);
};
