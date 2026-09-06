import 'package:flutter_test/flutter_test.dart';
import 'package:oyster_mushroom_manager/error_state.dart';

void main() {
  test('offline state shows the required reconnect message', () {
    final message = webViewErrorMessage(offline: true, mainFrameError: false);

    expect(message.title, 'No internet connection.');
    expect(message.detail, 'Please reconnect and try again.');
  });

  test('server errors are not mislabeled as no internet', () {
    final message = webViewErrorMessage(offline: false, mainFrameError: true);

    expect(message.title, 'Unable to load Oyster Mushroom.');
    expect(message.detail, contains('temporarily unavailable'));
  });

  test('offline state takes priority when both flags are set', () {
    final message = webViewErrorMessage(offline: true, mainFrameError: true);

    expect(message.title, 'No internet connection.');
  });

  test(
    'load errors distinguish connectivity failures from server failures',
    () {
      expect(
        webViewFailureForLoadError(
          connectivityOffline: false,
          webViewReportedOffline: true,
        ),
        WebViewFailure.offline,
      );
      expect(
        webViewFailureForLoadError(
          connectivityOffline: true,
          webViewReportedOffline: false,
        ),
        WebViewFailure.offline,
      );
      expect(
        webViewFailureForLoadError(
          connectivityOffline: false,
          webViewReportedOffline: false,
        ),
        WebViewFailure.server,
      );
    },
  );

  test('no failure has no overlay message', () {
    expect(messageForWebViewFailure(WebViewFailure.none), isNull);
    expect(
      messageForWebViewFailure(WebViewFailure.server)?.title,
      'Unable to load Oyster Mushroom.',
    );
  });
}
