// ===========================================================================
// PLACEHOLDER FIREBASE CONFIGURATION — NOT REAL CREDENTIALS
// ===========================================================================
//
// Every value below is a marked placeholder. The app will NOT connect to
// Firebase until they are replaced.
//
// Generate the real file instead of editing this one by hand:
//
//     dart pub global activate flutterfire_cli
//     flutterfire configure --project=<your-firebase-project>
//
// That overwrites this file with the real values for every platform you
// select. Firebase web config is not secret — it ships in the JS bundle of
// every Firebase web app — but it is environment-specific, so it does not
// belong in version control for a project with more than one environment.
// Keep the generated file out of git and generate it in CI, or accept it as
// committed config and know what you are accepting.
//
// UNVERIFIED: the exact set of named parameters on FirebaseOptions can gain
// fields between firebase_core majors. If the analyzer complains about a
// missing or unknown named argument here, regenerate with flutterfire rather
// than patching.
// ===========================================================================

import 'package:firebase_core/firebase_core.dart' show FirebaseOptions;
import 'package:flutter/foundation.dart'
    show TargetPlatform, defaultTargetPlatform, kIsWeb;

/// Platform-appropriate [FirebaseOptions] for BAROGROOVE.
class DefaultFirebaseOptions {
  const DefaultFirebaseOptions._();

  static FirebaseOptions get currentPlatform {
    if (kIsWeb) return web;
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return android;
      case TargetPlatform.iOS:
        return ios;
      case TargetPlatform.macOS:
        return macos;
      case TargetPlatform.windows:
      case TargetPlatform.linux:
      case TargetPlatform.fuchsia:
        throw UnsupportedError(
          'BAROGROOVE has no Firebase configuration for '
          '$defaultTargetPlatform. Run `flutterfire configure` and select it.',
        );
    }
  }

  /// True when the placeholders have not been replaced. `main()` checks this
  /// and shows a configuration screen rather than a stack trace.
  static bool get isPlaceholder =>
      web.apiKey.startsWith('REPLACE_ME') ||
      web.projectId.startsWith('REPLACE_ME');

  // -------------------------------------------------------------------------
  // WEB — served from bg.netdev.be via Firebase Hosting
  // -------------------------------------------------------------------------
  static const FirebaseOptions web = FirebaseOptions(
    apiKey: 'REPLACE_ME_WEB_API_KEY',
    appId: 'REPLACE_ME_WEB_APP_ID', // 1:000000000000:web:0000000000000000
    messagingSenderId: 'REPLACE_ME_SENDER_ID',
    projectId: 'REPLACE_ME_PROJECT_ID',
    authDomain: 'REPLACE_ME_PROJECT_ID.firebaseapp.com',
    storageBucket: 'REPLACE_ME_PROJECT_ID.appspot.com',
    // Remember to add bg.netdev.be to Firebase Auth → Settings → Authorised
    // domains, or the Google sign-in popup will be rejected in production.
  );

  // -------------------------------------------------------------------------
  // ANDROID
  // -------------------------------------------------------------------------
  static const FirebaseOptions android = FirebaseOptions(
    apiKey: 'REPLACE_ME_ANDROID_API_KEY',
    appId: 'REPLACE_ME_ANDROID_APP_ID',
    messagingSenderId: 'REPLACE_ME_SENDER_ID',
    projectId: 'REPLACE_ME_PROJECT_ID',
    storageBucket: 'REPLACE_ME_PROJECT_ID.appspot.com',
  );

  // -------------------------------------------------------------------------
  // iOS
  // -------------------------------------------------------------------------
  static const FirebaseOptions ios = FirebaseOptions(
    apiKey: 'REPLACE_ME_IOS_API_KEY',
    appId: 'REPLACE_ME_IOS_APP_ID',
    messagingSenderId: 'REPLACE_ME_SENDER_ID',
    projectId: 'REPLACE_ME_PROJECT_ID',
    storageBucket: 'REPLACE_ME_PROJECT_ID.appspot.com',
    iosBundleId: 'be.netdev.bg.barogroove',
  );

  // -------------------------------------------------------------------------
  // macOS
  // -------------------------------------------------------------------------
  static const FirebaseOptions macos = FirebaseOptions(
    apiKey: 'REPLACE_ME_MACOS_API_KEY',
    appId: 'REPLACE_ME_MACOS_APP_ID',
    messagingSenderId: 'REPLACE_ME_SENDER_ID',
    projectId: 'REPLACE_ME_PROJECT_ID',
    storageBucket: 'REPLACE_ME_PROJECT_ID.appspot.com',
    iosBundleId: 'be.netdev.bg.barogroove',
  );
}
