// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:async';
import 'dart:html' as html;
import 'dart:js' as js;

/// Web implementation of Speech Recognition (Speech-to-Text) and Speech Synthesis (Text-to-Speech).
class VoiceIo {
  VoiceIo({
    required this.onTranscript,
    required this.onListeningChanged,
    required this.onSpeakingChanged,
    required this.onError,
  }) {
    _initRecognition();
  }

  final void Function(String text, bool isFinal) onTranscript;
  final void Function(bool isListening) onListeningChanged;
  final void Function(bool isSpeaking) onSpeakingChanged;
  final void Function(String error) onError;

  js.JsObject? _recognition;
  bool _isListening = false;

  bool get isSupported => _recognition != null;

  void _initRecognition() {
    try {
      final js.JsObject win = js.context;
      dynamic ctor = win['SpeechRecognition'] ?? win['webkitSpeechRecognition'];
      if (ctor != null) {
        final js.JsObject rec = js.JsObject(ctor as js.JsFunction);
        rec['continuous'] = false;
        rec['interimResults'] = true;
        rec['lang'] = 'en-US';

        rec['onstart'] = js.allowInterop((dynamic _) {
          _isListening = true;
          onListeningChanged(true);
        });

        rec['onend'] = js.allowInterop((dynamic _) {
          _isListening = false;
          onListeningChanged(false);
        });

        rec['onerror'] = js.allowInterop((dynamic event) {
          _isListening = false;
          onListeningChanged(false);
          final String err = event?['error']?.toString() ?? 'unknown';
          if (err != 'no-speech' && err != 'aborted') {
            onError('Microphone error ($err). Check browser mic permissions.');
          }
        });

        rec['onresult'] = js.allowInterop((dynamic event) {
          try {
            final dynamic results = event['results'];
            if (results == null) return;
            final int length = (results['length'] as num?)?.toInt() ?? 0;
            String combined = '';
            bool isFinal = false;
            for (int i = 0; i < length; i++) {
              final dynamic res = results[i];
              final dynamic alt = res[0];
              final String transcript = alt?['transcript']?.toString() ?? '';
              combined += transcript;
              if (res['isFinal'] == true) {
                isFinal = true;
              }
            }
            if (combined.trim().isNotEmpty) {
              onTranscript(combined.trim(), isFinal);
            }
          } catch (_) {}
        });

        _recognition = rec;
      }
    } catch (_) {
      _recognition = null;
    }
  }

  void startListening() {
    stopSpeaking();
    if (_recognition == null) {
      _initRecognition();
    }
    if (_recognition == null) {
      onError(
        'Speech recognition is not supported in this browser tab. Use the quick voice prompt chips or type below.',
      );
      return;
    }
    try {
      if (_isListening) {
        _recognition!.callMethod('stop');
      } else {
        _recognition!.callMethod('start');
      }
    } catch (e) {
      onError('Could not start microphone: $e');
    }
  }

  void stopListening() {
    if (_recognition != null && _isListening) {
      try {
        _recognition!.callMethod('stop');
      } catch (_) {}
    }
    _isListening = false;
    onListeningChanged(false);
  }

  Future<void> speak(String text, {bool muted = false}) async {
    if (muted || text.trim().isEmpty) return;
    try {
      final html.SpeechSynthesis? synth = html.window.speechSynthesis;
      if (synth == null) return;
      synth.cancel();

      final html.SpeechSynthesisUtterance utterance =
          html.SpeechSynthesisUtterance(text);
      utterance.lang = 'en-US';
      utterance.rate = 1.02;
      utterance.pitch = 0.96;

      // Pick an expressive natural English voice if available
      final List<html.SpeechSynthesisVoice> voices = synth.getVoices();
      for (final html.SpeechSynthesisVoice v in voices) {
        final String name = (v.name ?? '').toLowerCase();
        if (name.contains('natural') ||
            name.contains('google uk english male') ||
            name.contains('google us english') ||
            name.contains('siri')) {
          utterance.voice = v;
          break;
        }
      }

      utterance.onStart.listen((_) => onSpeakingChanged(true));
      utterance.onEnd.listen((_) => onSpeakingChanged(false));
      utterance.onError.listen((_) => onSpeakingChanged(false));

      synth.speak(utterance);
    } catch (_) {
      onSpeakingChanged(false);
    }
  }

  void stopSpeaking() {
    try {
      html.window.speechSynthesis?.cancel();
    } catch (_) {}
    onSpeakingChanged(false);
  }

  void dispose() {
    stopListening();
    stopSpeaking();
  }
}
