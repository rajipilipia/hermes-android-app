/* Packaged native lifecycle hook. No tokens, network, storage or arbitrary native bridge. */
(function () {
  'use strict';
  if (window.top !== window || window.__hermesNativeLifecycle) return;
  // Parser-installed before renderer scripts. Visibility alone never grants native
  // foreground authority, including the cold visible-document case.
  var nativePaused = true;
  var paused = true;
  // True only while native confirmed a user-started Codex Live call (microphone foreground
  // service running). Then, and only then, the call's tracks and audio survive a pause.
  var call = false;
  var generation = 0;
  var tracks = new Set();
  var devices = window.navigator.mediaDevices;
  if (devices && typeof devices.getUserMedia === 'function') {
    var capture = devices.getUserMedia.bind(devices);
    devices.getUserMedia = function (constraints) {
      if (paused) return Promise.reject(new DOMException('Return to Hermes to record.', 'NotAllowedError'));
      var admitted = generation;
      return capture(constraints).then(function (stream) {
        if (paused || admitted !== generation) {
          stream.getTracks().forEach(function (track) { track.stop(); });
          throw new DOMException('Recording cancelled while Hermes was backgrounded.', 'AbortError');
        }
        stream.getTracks().forEach(function (track) {
          tracks.add(track);
          track.addEventListener('ended', function () { tracks.delete(track); }, { once: true });
        });
        return stream;
      });
    };
  }
  function stopCapture() {
    generation++;
    tracks.forEach(function (track) { track.stop(); });
    tracks.clear();
    window.document.querySelectorAll('audio,video').forEach(function (media) { media.pause(); });
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }
  function update() {
    paused = nativePaused || window.document.visibilityState === 'hidden';
    if (paused && !call) stopCapture();
    window.dispatchEvent(new window.CustomEvent('hermes:native-lifecycle', { detail: { state: paused ? 'pause' : 'resume' } }));
  }
  function lifecycle(state) {
    if (state === 'call-on' || state === 'call-off') {
      call = state === 'call-on';
      // The call ended while Hermes is in the background: the normal pause rules apply at once.
      if (!call && paused) stopCapture();
      return;
    }
    if (state !== 'pause' && state !== 'resume') return;
    nativePaused = state === 'pause';
    update();
  }
  Object.defineProperty(window, '__hermesNativeLifecycle', { value: lifecycle, configurable: false });
  window.document.addEventListener('visibilitychange', update);
})();
