import 'dart:async';

/// VM/Stub implementation of Web Speech Recognition & Speech Synthesis.
class VoiceIo {
  VoiceIo({
    required this.onTranscript,
    required this.onListeningChanged,
    required this.onSpeakingChanged,
    required this.onError,
  });

  final void Function(String text, bool isFinal) onTranscript;
  final void Function(bool isListening) onListeningChanged;
  final void Function(bool isSpeaking) onSpeakingChanged;
  final void Function(String error) onError;

  bool get isSupported => false;

  void startListening() {
    onError('Voice recognition is available in the Web browser.');
  }

  void stopListening() {
    onListeningChanged(false);
  }

  Future<void> speak(String text, {bool muted = false}) async {
    if (muted) return;
    onSpeakingChanged(true);
    await Future<void>.delayed(const Duration(milliseconds: 800));
    onSpeakingChanged(false);
  }

  void stopSpeaking() {
    onSpeakingChanged(false);
  }

  void dispose() {}
}
