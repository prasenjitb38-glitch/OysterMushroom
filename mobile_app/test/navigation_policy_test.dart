import 'package:flutter_test/flutter_test.dart';
import 'package:oyster_mushroom_manager/navigation_policy.dart';

void main() {
  group('trusted application navigation', () {
    test('allows only the exact HTTPS application origin', () {
      expect(isTrustedAppUrl(Uri.parse(appBaseUrl)), isTrue);
      expect(
        isTrustedAppUrl(Uri.parse('$appBaseUrl/invoice/1?download=1')),
        isTrue,
      );
      expect(
        isTrustedAppUrl(Uri.parse('http://oystermushroom.onrender.com')),
        isFalse,
      );
      expect(
        isTrustedAppUrl(
          Uri.parse('https://oystermushroom.onrender.com:444/invoice/1'),
        ),
        isFalse,
      );
      expect(
        isTrustedAppUrl(Uri.parse('https://evil.oystermushroom.onrender.com')),
        isFalse,
      );
      expect(
        isTrustedAppUrl(
          Uri.parse('https://oystermushroom.onrender.com.evil.test'),
        ),
        isFalse,
      );
      expect(
        isTrustedAppUrl(Uri.parse('https://user@oystermushroom.onrender.com')),
        isFalse,
      );
    });

    test('recognizes system and external links', () {
      expect(isSystemUrl(Uri.parse('tel:+919999999999')), isTrue);
      expect(isSystemUrl(Uri.parse('mailto:test@example.com')), isTrue);
      expect(isExternalWebUrl(Uri.parse('https://example.com')), isTrue);
      expect(isExternalWebUrl(Uri.parse(appBaseUrl)), isFalse);
      expect(isExternalWebUrl(Uri.parse('ftp://example.com/file')), isFalse);
      expect(isExternalWebUrl(Uri.parse('javascript:alert(1)')), isFalse);
    });
  });
}
