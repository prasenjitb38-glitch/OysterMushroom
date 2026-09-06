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
    final directory = Directory(
      '${(await getApplicationDocumentsDirectory()).path}${Platform.pathSeparator}downloads',
    );
    final file = await saveTrustedDownload(
      _client,
      uri,
      directory,
      cookieHeader: cookieHeader,
    );
    final openResult = await OpenFilex.open(file.path);
    return DownloadResult(path: file.path, openResult: openResult);
  }
}

Future<http.StreamedResponse> fetchTrustedDownload(
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
    final isRedirectStatus = const {
      301,
      302,
      303,
      307,
      308,
    }.contains(streamed.statusCode);
    if (!isRedirectStatus) {
      return streamed;
    }
    final location = streamed.headers['location'];
    await streamed.stream.drain<void>();
    if (location == null || location.trim().isEmpty) {
      throw HttpException(
        'Download redirect has no destination.',
        uri: current,
      );
    }
    if (redirect == maxRedirects) {
      break;
    }
    current = current.resolve(location);
    if (!isTrustedAppUrl(current)) {
      throw HttpException('Blocked untrusted download redirect.', uri: current);
    }
  }
  throw HttpException('Too many download redirects.', uri: start);
}

Future<File> saveTrustedDownload(
  http.Client client,
  Uri start,
  Directory directory, {
  String cookieHeader = '',
  int maxRedirects = 5,
}) async {
  final response = await fetchTrustedDownload(
    client,
    start,
    cookieHeader: cookieHeader,
    maxRedirects: maxRedirects,
  );
  if (response.statusCode < 200 || response.statusCode >= 300) {
    await response.stream.drain<void>();
    throw HttpException(
      'Download failed with status ${response.statusCode}.',
      uri: start,
    );
  }

  final responseUri = response.request?.url ?? start;
  await directory.create(recursive: true);
  final fileName = safeDownloadFileName(response.headers, responseUri);
  final file = await availableDownloadFile(directory, fileName);
  final sink = file.openWrite();
  var byteCount = 0;
  var sinkClosed = false;
  try {
    await for (final chunk in response.stream) {
      byteCount += chunk.length;
      sink.add(chunk);
    }
    await sink.flush();
    await sink.close();
    sinkClosed = true;
    if (byteCount == 0) {
      throw HttpException('The downloaded file is empty.', uri: responseUri);
    }
    return file;
  } catch (_) {
    if (!sinkClosed) {
      try {
        await sink.close();
      } on Object {
        // Preserve the download error; the partial file is removed below.
      }
    }
    try {
      if (await file.exists()) {
        await file.delete();
      }
    } on FileSystemException {
      // Preserve the original download error.
    }
    rethrow;
  }
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
