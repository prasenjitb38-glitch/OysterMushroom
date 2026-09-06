import 'dart:io';

import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import 'navigation_policy.dart';

class DownloadResult {
  const DownloadResult({required this.path, required this.openResult});

  final String path;
  final OpenResult openResult;
}

class DownloadService {
  DownloadService({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;

  Future<DownloadResult> downloadAndOpen(WebUri webUri) async {
    final uri = Uri.parse(webUri.toString());
    if (!isTrustedAppUrl(uri)) {
      throw const HttpException('Blocked untrusted download address.');
    }

    final cookies = await CookieManager.instance().getCookies(url: webUri);
    final cookieHeader = cookies
        .map((cookie) => '${cookie.name}=${cookie.value}')
        .join('; ');
    final response = await fetchTrustedDownload(
      _client,
      uri,
      cookieHeader: cookieHeader,
    );
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw HttpException(
        'Download failed with status ${response.statusCode}.',
        uri: uri,
      );
    }
    if (response.bodyBytes.isEmpty) {
      throw HttpException('The downloaded file is empty.', uri: uri);
    }

    final directory = Directory(
      '${(await getApplicationDocumentsDirectory()).path}${Platform.pathSeparator}downloads',
    );
    await directory.create(recursive: true);
    final fileName = safeDownloadFileName(response.headers, uri);
    final file = await availableDownloadFile(directory, fileName);
    await file.writeAsBytes(response.bodyBytes, flush: true);
    final openResult = await OpenFilex.open(file.path);
    return DownloadResult(path: file.path, openResult: openResult);
  }
}

Future<http.Response> fetchTrustedDownload(
  http.Client client,
  Uri start, {
  String cookieHeader = '',
  int maxRedirects = 5,
}) async {
  var current = start;
  for (var redirect = 0; redirect <= maxRedirects; redirect++) {
    if (!isTrustedAppUrl(current)) {
      throw const HttpException('Blocked untrusted download address.');
    }
    final request = http.Request('GET', current)
      ..followRedirects = false
      ..headers.addAll({
        'Accept': '*/*',
        if (cookieHeader.isNotEmpty) 'Cookie': cookieHeader,
      });
    final streamed = await client.send(request);
    final response = await http.Response.fromStream(streamed);
    final isRedirectStatus = const {
      301,
      302,
      303,
      307,
      308,
    }.contains(response.statusCode);
    if (!isRedirectStatus) {
      return response;
    }
    if (redirect == maxRedirects) {
      break;
    }
    final location = response.headers['location'];
    if (location == null || location.trim().isEmpty) {
      throw HttpException(
        'Download redirect has no destination.',
        uri: current,
      );
    }
    current = current.resolve(location);
    if (!isTrustedAppUrl(current)) {
      throw HttpException('Blocked untrusted download redirect.', uri: current);
    }
  }
  throw HttpException('Too many download redirects.', uri: start);
}

Future<File> availableDownloadFile(Directory directory, String fileName) async {
  var candidate = File('${directory.path}${Platform.pathSeparator}$fileName');
  if (!await candidate.exists()) {
    return candidate;
  }

  final extensionIndex = fileName.lastIndexOf('.');
  final hasExtension = extensionIndex > 0;
  final stem = hasExtension ? fileName.substring(0, extensionIndex) : fileName;
  final extension = hasExtension ? fileName.substring(extensionIndex) : '';
  for (var suffix = 2; suffix < 10000; suffix++) {
    candidate = File(
      '${directory.path}${Platform.pathSeparator}$stem ($suffix)$extension',
    );
    if (!await candidate.exists()) {
      return candidate;
    }
  }
  throw const FileSystemException('Unable to choose a download filename.');
}

String? _headerValue(Map<String, String> headers, String name) {
  for (final entry in headers.entries) {
    if (entry.key.toLowerCase() == name) {
      return entry.value;
    }
  }
  return null;
}

String? _contentDispositionFileName(String disposition) {
  final encoded = RegExp(
    r"""(?:^|;)\s*filename\*\s*=\s*(?:UTF-8'[^']*')?([^;]+)""",
    caseSensitive: false,
  ).firstMatch(disposition);
  if (encoded != null) {
    return encoded.group(1)?.trim().replaceAll(RegExp(r'^"|"$'), '');
  }
  final quoted = RegExp(
    r'(?:^|;)\s*filename\s*=\s*"([^"]*)"',
    caseSensitive: false,
  ).firstMatch(disposition);
  if (quoted != null) {
    return quoted.group(1);
  }
  return RegExp(
    r'(?:^|;)\s*filename\s*=\s*([^;]+)',
    caseSensitive: false,
  ).firstMatch(disposition)?.group(1)?.trim();
}

String _truncateFileName(String value, int maxLength) {
  if (value.length <= maxLength) {
    return value;
  }
  final extensionIndex = value.lastIndexOf('.');
  final extension = extensionIndex > 0 ? value.substring(extensionIndex) : '';
  final stemLength = maxLength - extension.length;
  return '${value.substring(0, stemLength > 0 ? stemLength : maxLength)}'
      '${stemLength > 0 ? extension : ''}';
}

String safeDownloadFileName(Map<String, String> headers, Uri uri) {
  final disposition = _headerValue(headers, 'content-disposition') ?? '';
  final rawCandidate =
      (_contentDispositionFileName(disposition) ??
              uri.pathSegments.lastOrNull ??
              'download')
          .trim();
  String candidate;
  try {
    candidate = Uri.decodeComponent(rawCandidate);
  } on FormatException {
    candidate = rawCandidate;
  }
  candidate = candidate.split(RegExp(r'[/\\]')).last;
  final safe = candidate.replaceAll(RegExp(r'[<>:"/\\|?*\x00-\x1F]'), '_');
  var normalized = safe.replaceAll(RegExp(r'^[. ]+|[. ]+$'), '');
  final stem = normalized.split('.').first.toUpperCase();
  const reservedWindowsNames = {
    'CON',
    'PRN',
    'AUX',
    'NUL',
    'COM1',
    'COM2',
    'COM3',
    'COM4',
    'COM5',
    'COM6',
    'COM7',
    'COM8',
    'COM9',
    'LPT1',
    'LPT2',
    'LPT3',
    'LPT4',
    'LPT5',
    'LPT6',
    'LPT7',
    'LPT8',
    'LPT9',
  };
  if (reservedWindowsNames.contains(stem)) {
    normalized = '_$normalized';
  }
  if (normalized.isEmpty) {
    return 'download_${DateTime.now().millisecondsSinceEpoch}';
  }
  return _truncateFileName(normalized, 180);
}

extension _LastOrNull<T> on List<T> {
  T? get lastOrNull => isEmpty ? null : last;
}
