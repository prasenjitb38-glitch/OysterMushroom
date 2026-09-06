import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oyster_mushroom_manager/download_service.dart';
import 'package:oyster_mushroom_manager/navigation_policy.dart';

class _StreamClient extends http.BaseClient {
  _StreamClient(this.handler);

  final Future<http.StreamedResponse> Function(http.BaseRequest) handler;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) =>
      handler(request);
}

void main() {
  group('safeDownloadFileName', () {
    test('uses and decodes a content-disposition filename', () {
      final name = safeDownloadFileName({
        'content-disposition':
            "attachment; filename*=UTF-8''Oyster%20Invoice.pdf",
      }, Uri.parse('https://oystermushroom.onrender.com/invoice/1.pdf'));

      expect(name, 'Oyster Invoice.pdf');
    });

    test('removes path separators and unsafe filename characters', () {
      final name = safeDownloadFileName({
        'content-disposition': 'attachment; filename="../bad:name?.db"',
      }, Uri.parse('https://oystermushroom.onrender.com/backup/download'));

      expect(name, 'bad_name_.db');
      expect(name, isNot(contains('/')));
      expect(name, isNot(contains(r'\')));
    });

    test('falls back to the URL path segment', () {
      final name = safeDownloadFileName(
        const {},
        Uri.parse('https://oystermushroom.onrender.com/reports/export.csv'),
      );

      expect(name, 'export.csv');
    });

    test('handles case-insensitive headers and Windows reserved names', () {
      final name = safeDownloadFileName({
        'Content-Disposition': 'attachment; filename="CON.pdf"',
      }, Uri.parse('$appBaseUrl/download'));

      expect(name, '_CON.pdf');
    });

    test('limits long names while retaining the extension', () {
      final name = safeDownloadFileName({
        'content-disposition': 'attachment; filename="${'a' * 250}.pdf"',
      }, Uri.parse('$appBaseUrl/download'));

      expect(name.length, 180);
      expect(name, endsWith('.pdf'));
    });
  });

  group('fetchTrustedDownload', () {
    test(
      'forwards session cookies across trusted relative redirects',
      () async {
        final requests = <http.Request>[];
        final client = MockClient((request) async {
          requests.add(request);
          if (request.url.path == '/start') {
            return http.Response('', 302, headers: {'location': '/file.pdf'});
          }
          return http.Response('pdf', 200);
        });

        final response = await fetchTrustedDownload(
          client,
          Uri.parse('$appBaseUrl/start'),
          cookieHeader: 'session=secret',
        );

        expect(response.statusCode, 200);
        expect(await response.stream.bytesToString(), 'pdf');
        expect(requests.map((request) => request.url.path), [
          '/start',
          '/file.pdf',
        ]);
        expect(
          requests.every(
            (request) => request.headers['Cookie'] == 'session=secret',
          ),
          isTrue,
        );
      },
    );

    test('blocks an untrusted initial address without sending it', () async {
      var sent = false;
      final client = MockClient((request) async {
        sent = true;
        return http.Response('unexpected', 200);
      });

      await expectLater(
        fetchTrustedDownload(client, Uri.parse('https://example.com/file.pdf')),
        throwsA(isA<HttpException>()),
      );
      expect(sent, isFalse);
    });

    test('blocks redirects away from the exact trusted host', () async {
      final client = MockClient(
        (_) async => http.Response(
          '',
          302,
          headers: {'location': 'https://example.com/stolen.pdf'},
        ),
      );

      await expectLater(
        fetchTrustedDownload(client, Uri.parse('$appBaseUrl/start')),
        throwsA(
          isA<HttpException>().having(
            (error) => error.message,
            'message',
            contains('redirect'),
          ),
        ),
      );
    });

    test('rejects redirects with no location', () async {
      final client = MockClient((_) async => http.Response('', 302));

      await expectLater(
        fetchTrustedDownload(client, Uri.parse('$appBaseUrl/start')),
        throwsA(
          isA<HttpException>().having(
            (error) => error.message,
            'message',
            contains('no destination'),
          ),
        ),
      );
    });

    test('enforces the redirect limit', () async {
      var requests = 0;
      final client = MockClient((request) async {
        requests++;
        return http.Response(
          '',
          302,
          headers: {'location': '/redirect-$requests'},
        );
      });

      await expectLater(
        fetchTrustedDownload(
          client,
          Uri.parse('$appBaseUrl/start'),
          maxRedirects: 1,
        ),
        throwsA(
          isA<HttpException>().having(
            (error) => error.message,
            'message',
            contains('Too many'),
          ),
        ),
      );
      expect(requests, 2);
    });
  });

  group('saveTrustedDownload', () {
    late Directory directory;

    setUp(() async {
      directory = await Directory.systemTemp.createTemp(
        'oyster_stream_download_',
      );
    });

    tearDown(() async {
      if (await directory.exists()) {
        await directory.delete(recursive: true);
      }
    });

    test('streams a nonempty response into the selected file', () async {
      final client = _StreamClient(
        (request) async => http.StreamedResponse(
          Stream.fromIterable([
            Uint8List.fromList([1, 2]),
            Uint8List.fromList([3, 4]),
          ]),
          200,
          request: request,
          headers: {
            'content-disposition': 'attachment; filename="invoice.pdf"',
          },
        ),
      );

      final file = await saveTrustedDownload(
        client,
        Uri.parse('$appBaseUrl/download'),
        directory,
      );

      expect(file.path, endsWith('invoice.pdf'));
      expect(await file.readAsBytes(), [1, 2, 3, 4]);
    });

    test('rejects non-2xx responses without creating a file', () async {
      final client = MockClient((_) async => http.Response('denied', 403));

      await expectLater(
        saveTrustedDownload(
          client,
          Uri.parse('$appBaseUrl/download'),
          directory,
        ),
        throwsA(
          isA<HttpException>().having(
            (error) => error.message,
            'message',
            contains('403'),
          ),
        ),
      );
      expect(directory.listSync(), isEmpty);
    });

    test('rejects an empty body and removes the output file', () async {
      final client = MockClient((_) async => http.Response('', 200));

      await expectLater(
        saveTrustedDownload(
          client,
          Uri.parse('$appBaseUrl/empty.pdf'),
          directory,
        ),
        throwsA(
          isA<HttpException>().having(
            (error) => error.message,
            'message',
            contains('empty'),
          ),
        ),
      );
      expect(directory.listSync(), isEmpty);
    });

    test('removes a partial file when the response stream fails', () async {
      Stream<List<int>> failingStream() async* {
        yield [1, 2, 3];
        throw StateError('connection lost');
      }

      final client = _StreamClient(
        (request) async => http.StreamedResponse(
          failingStream(),
          200,
          request: request,
          headers: {
            'content-disposition': 'attachment; filename="partial.pdf"',
          },
        ),
      );

      await expectLater(
        saveTrustedDownload(
          client,
          Uri.parse('$appBaseUrl/download'),
          directory,
        ),
        throwsA(isA<StateError>()),
      );
      expect(directory.listSync(), isEmpty);
    });
  });

  test('availableDownloadFile does not overwrite an existing file', () async {
    final directory = await Directory.systemTemp.createTemp('oyster_download_');
    addTearDown(() => directory.delete(recursive: true));
    await File(
      '${directory.path}${Platform.pathSeparator}invoice.pdf',
    ).writeAsString('existing');

    final available = await availableDownloadFile(directory, 'invoice.pdf');

    expect(
      available.path,
      endsWith('${Platform.pathSeparator}invoice (2).pdf'),
    );
  });
}
