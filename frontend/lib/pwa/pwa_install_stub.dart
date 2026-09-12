import 'dart:async';

class PwaInstallBridge {
  PwaInstallBridge({void Function()? onStateChanged});

  bool get isInstallable => false;
  bool get isStandalone => false;
  bool get isIosSafari => false;

  Future<String> triggerInstall() async => 'unavailable';
  void dispose() {}
}
