const appBaseUrl = 'https://oystermushroom.onrender.com';
const appHost = 'oystermushroom.onrender.com';

bool isTrustedAppUrl(Uri uri) {
  return uri.scheme == 'https' &&
      uri.host.toLowerCase() == appHost &&
      !uri.hasPort &&
      uri.userInfo.isEmpty;
}

bool isSystemUrl(Uri uri) {
  return uri.scheme == 'tel' || uri.scheme == 'mailto';
}

bool isExternalWebUrl(Uri uri) {
  return (uri.scheme == 'https' || uri.scheme == 'http') &&
      !isTrustedAppUrl(uri);
}

bool canLaunchExternalNavigation({
  required bool isMainFrame,
  required bool isNewWindow,
  required bool isUserInitiated,
}) {
  return isUserInitiated && (isMainFrame || isNewWindow);
}
