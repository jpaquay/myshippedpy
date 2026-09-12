// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:async';
import 'dart:html' as html;
import 'dart:js' as js;

class PwaInstallBridge {
  PwaInstallBridge({this.onStateChanged}) {
    _subInstallable = html.window.on['barogroove-pwa-installable'].listen((_) {
      onStateChanged?.call();
    });
    _subInstalled = html.window.on['barogroove-pwa-installed'].listen((_) {
      onStateChanged?.call();
    });
  }

  final void Function()? onStateChanged;
  StreamSubscription<html.Event>? _subInstallable;
  StreamSubscription<html.Event>? _subInstalled;

  bool get isInstallable {
    try {
      final dynamic res = js.context.callMethod('isBarogroovePwaInstallable');
      return res == true;
    } catch (_) {
      return false;
    }
  }

  bool get isStandalone {
    try {
      final dynamic res = js.context.callMethod('isBarogrooveStandalone');
      return res == true;
    } catch (_) {
      return false;
    }
  }

  bool get isIosSafari {
    final String ua = html.window.navigator.userAgent.toLowerCase();
    final bool isIos = ua.contains('iphone') || ua.contains('ipad') || ua.contains('ipod');
    return isIos && !isStandalone;
  }

  Future<String> triggerInstall() async {
    try {
      final dynamic promise = js.context.callMethod('triggerBarogroovePwaInstall');
      if (promise != null) {
        final Completer<String> completer = Completer<String>();
        final js.JsObject jsPromise = promise as js.JsObject;
        jsPromise.callMethod('then', <dynamic>[
          js.allowInterop((dynamic result) {
            completer.complete(result?.toString() ?? 'dismissed');
          }),
        ]);
        return await completer.future.timeout(
          const Duration(seconds: 30),
          onTimeout: () => 'timeout',
        );
      }
      return 'unavailable';
    } catch (_) {
      return 'error';
    }
  }

  void dispose() {
    _subInstallable?.cancel();
    _subInstalled?.cancel();
  }
}
