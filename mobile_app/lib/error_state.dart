class WebViewErrorMessage {
  const WebViewErrorMessage({required this.title, required this.detail});

  final String title;
  final String detail;
}

enum WebViewFailure { none, offline, server }

WebViewFailure webViewFailureForLoadError({
  required bool connectivityOffline,
  required bool webViewReportedOffline,
}) {
  return connectivityOffline || webViewReportedOffline
      ? WebViewFailure.offline
      : WebViewFailure.server;
}

WebViewErrorMessage webViewErrorMessage({
  required bool offline,
  required bool mainFrameError,
}) {
  if (offline) {
    return const WebViewErrorMessage(
      title: 'No internet connection.',
      detail: 'Please reconnect and try again.',
    );
  }
  if (mainFrameError) {
    return const WebViewErrorMessage(
      title: 'Unable to load Oyster Mushroom.',
      detail: 'The server may be temporarily unavailable. Please try again.',
    );
  }
  throw ArgumentError('An offline or page error state is required.');
}

WebViewErrorMessage? messageForWebViewFailure(WebViewFailure failure) {
  switch (failure) {
    case WebViewFailure.none:
      return null;
    case WebViewFailure.offline:
      return webViewErrorMessage(offline: true, mainFrameError: false);
    case WebViewFailure.server:
      return webViewErrorMessage(offline: false, mainFrameError: true);
  }
}
