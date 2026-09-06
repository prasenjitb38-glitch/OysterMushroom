import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:oyster_mushroom_manager/download_service.dart';
import 'package:oyster_mushroom_manager/navigation_policy.dart';

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
