# Oyster Mushroom Manager mobile wrapper

This Flutter project is a thin, secure WebView wrapper around
`https://oystermushroom.onrender.com`. The Flask application remains the only
business application and database.

## Features

- Exact responsive web application inside Android and iOS
- Existing Flask login, cookies, sessions, roles, forms, and CSRF protection
- HTTPS-only in-app navigation restricted to the production host
- External browser handling for other web origins and system handling for
  telephone/email links
- Authenticated PDF, CSV, and backup downloads saved to app documents
- WebView file chooser support for backup restore/upload forms
- Same-window handling for invoice links that use `target="_blank"`
- Pull-to-refresh, loading progress, Android history-aware back navigation, and
  separate offline/server error messages with connectivity-aware retry

## App identity and artwork

The user-facing name is **Oyster Mushroom Manager** and the Android application
ID/iOS bundle ID is `com.oystermushroom.manager`. The source artwork is
`assets/app_icon.png`; launcher icons and the dark-green native splash are
configured in `pubspec.yaml`.

Regenerate platform artwork after replacing the source image:

```sh
dart run flutter_launcher_icons
dart run flutter_native_splash:create
```

Commit the generated Android/iOS icon and splash resources, but never generated
build directories.

## Build

```sh
flutter pub get
flutter test
flutter analyze
flutter build apk --debug
flutter build appbundle --debug
```

Generated artifacts are placed under `build/app/outputs/`.
The debug APK is suitable for direct device testing. The debug AAB verifies the
bundle build pipeline but is not suitable for Google Play publication.

## Android release

The package identifier is `com.oystermushroom.manager`. Debug artifacts use the
standard local Flutter debug key. For Play Store release, configure a private
upload keystore outside source control and build a release Android App Bundle.
The checked-in release build is intentionally unsigned; never commit keystores
or signing passwords.

Useful artifact locations:

- `build/app/outputs/flutter-apk/app-debug.apk`
- `build/app/outputs/bundle/debug/app-debug.aab`

The WebView uses Android's system file chooser for HTML file inputs, including
the database restore form. Downloads are stored under the app documents
directory and opened with a compatible installed application.

## iOS

The bundle identifier is `com.oystermushroom.manager`. The complete iOS project
is under `ios/`, but final compilation, signing, archive, and device testing
require macOS, Xcode, an Apple Developer account, and provisioning profiles.
The iOS WebView uses the system document/photo picker for HTML uploads. User
selection through the document picker grants access to the selected file and
does not require broad Documents-folder permission. Camera and photo-library
usage descriptions cover the optional capture/photo choices. ATS continues to
reject arbitrary network loads.

Status: iOS project prepared; final signing/build requires macOS + Xcode.
