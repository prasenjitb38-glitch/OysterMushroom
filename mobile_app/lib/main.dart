import 'dart:async';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import 'package:open_filex/open_filex.dart';
import 'package:url_launcher/url_launcher.dart';

import 'download_service.dart';
import 'error_state.dart';
import 'navigation_policy.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const OysterMushroomApp());
}

class OysterMushroomApp extends StatelessWidget {
  const OysterMushroomApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Oyster Mushroom Manager',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF12372A)),
        useMaterial3: true,
      ),
      home: const WebAppScreen(),
    );
  }
}

class WebAppScreen extends StatefulWidget {
  const WebAppScreen({super.key});

  @override
  State<WebAppScreen> createState() => _WebAppScreenState();
}

class _WebAppScreenState extends State<WebAppScreen> {
  final _scaffoldKey = GlobalKey<ScaffoldState>();
  final _downloadService = DownloadService();
  InAppWebViewController? _webController;
  PullToRefreshController? _pullToRefreshController;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySubscription;
  WebViewFailure _failure = WebViewFailure.none;
  bool _connectivityOffline = false;
  bool _downloading = false;
  bool _initialLoadComplete = false;
  int _progress = 0;

  @override
  void initState() {
    super.initState();
    _pullToRefreshController = PullToRefreshController(
      settings: PullToRefreshSettings(
        color: const Color(0xFFE6B44A),
        backgroundColor: const Color(0xFF12372A),
      ),
      onRefresh: () async {
        final controller = _webController;
        if (controller == null) {
          await _pullToRefreshController?.endRefreshing();
          return;
        }
        if (Platform.isAndroid) {
          await controller.reload();
        } else {
          final current = await controller.getUrl();
          if (current != null) {
            await controller.loadUrl(urlRequest: URLRequest(url: current));
          }
        }
      },
    );
    _connectivitySubscription = Connectivity().onConnectivityChanged.listen(
      _onConnectivityChanged,
    );
    unawaited(_refreshConnectivity());
  }

  @override
  void dispose() {
    _connectivitySubscription?.cancel();
    super.dispose();
  }

  Future<bool> _refreshConnectivity() async {
    final results = await Connectivity().checkConnectivity();
    _onConnectivityChanged(results);
    return _connectivityOffline;
  }

  void _onConnectivityChanged(List<ConnectivityResult> results) {
    final offline =
        results.isEmpty ||
        results.every((result) => result == ConnectivityResult.none);
    if (!mounted || offline == _connectivityOffline) {
      return;
    }
    final wasOffline = _connectivityOffline;
    setState(() {
      _connectivityOffline = offline;
      if (offline) {
        _failure = WebViewFailure.offline;
      }
    });
    if (wasOffline &&
        !offline &&
        _failure == WebViewFailure.offline &&
        _initialLoadComplete) {
      unawaited(_retry());
    }
  }

  Future<void> _retry() async {
    final offline = await _refreshConnectivity();
    if (!mounted) {
      return;
    }
    if (offline) {
      setState(() => _failure = WebViewFailure.offline);
      return;
    }
    setState(() {
      _failure = WebViewFailure.none;
      _progress = 0;
    });
    final controller = _webController;
    if (controller == null) {
      return;
    }
    final current = await controller.getUrl();
    if (current != null && isTrustedAppUrl(Uri.parse(current.toString()))) {
      await controller.reload();
    } else {
      await controller.loadUrl(urlRequest: URLRequest(url: WebUri(appBaseUrl)));
    }
  }

  Future<NavigationActionPolicy> _handleNavigation(
    NavigationAction action,
  ) async {
    final webUri = action.request.url;
    if (webUri == null) {
      return NavigationActionPolicy.CANCEL;
    }
    final uri = Uri.parse(webUri.toString());
    if (isTrustedAppUrl(uri)) {
      return NavigationActionPolicy.ALLOW;
    }
    if (isSystemUrl(uri) || isExternalWebUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
    return NavigationActionPolicy.CANCEL;
  }

  Future<bool?> _handleNewWindow(CreateWindowAction action) async {
    final webUri = action.request.url;
    if (webUri == null) {
      return true;
    }
    final uri = Uri.parse(webUri.toString());
    if (isTrustedAppUrl(uri)) {
      await _webController?.loadUrl(urlRequest: URLRequest(url: webUri));
    } else if (isSystemUrl(uri) || isExternalWebUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
    return true;
  }

  Future<void> _download(DownloadStartRequest request) async {
    if (_downloading) {
      return;
    }
    setState(() => _downloading = true);
    try {
      final result = await _downloadService.downloadAndOpen(request.url);
      if (!mounted) {
        return;
      }
      final opened = result.openResult.type == ResultType.done;
      _showMessage(
        opened
            ? 'Download complete.'
            : 'Saved to ${result.path}. No compatible viewer opened.',
      );
    } catch (error) {
      if (mounted) {
        _showMessage('Download failed: $error');
      }
    } finally {
      if (mounted) {
        setState(() => _downloading = false);
      }
    }
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(
      _scaffoldKey.currentContext!,
    ).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _handleBack() async {
    final controller = _webController;
    if (controller != null && await controller.canGoBack()) {
      await controller.goBack();
      return;
    }
    await SystemNavigator.pop();
  }

  @override
  Widget build(BuildContext context) {
    final errorMessage = messageForWebViewFailure(_failure);
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, result) async {
        if (!didPop) {
          await _handleBack();
        }
      },
      child: Scaffold(
        key: _scaffoldKey,
        body: SafeArea(
          child: Stack(
            children: [
              InAppWebView(
                initialUrlRequest: URLRequest(url: WebUri(appBaseUrl)),
                initialSettings: InAppWebViewSettings(
                  javaScriptEnabled: true,
                  domStorageEnabled: true,
                  databaseEnabled: true,
                  sharedCookiesEnabled: true,
                  thirdPartyCookiesEnabled: false,
                  cacheEnabled: true,
                  clearCache: false,
                  supportMultipleWindows: true,
                  javaScriptCanOpenWindowsAutomatically: true,
                  useShouldOverrideUrlLoading: true,
                  useOnDownloadStart: true,
                  safeBrowsingEnabled: true,
                  allowsBackForwardNavigationGestures: true,
                  allowsInlineMediaPlayback: true,
                  mediaPlaybackRequiresUserGesture: false,
                  verticalScrollBarEnabled: true,
                  horizontalScrollBarEnabled: true,
                ),
                pullToRefreshController: _pullToRefreshController,
                onWebViewCreated: (controller) => _webController = controller,
                shouldOverrideUrlLoading: (controller, action) =>
                    _handleNavigation(action),
                onCreateWindow: (controller, action) =>
                    _handleNewWindow(action),
                onDownloadStartRequest: (controller, request) =>
                    _download(request),
                onLoadStart: (controller, url) {
                  if (mounted) {
                    setState(() {
                      if (!_connectivityOffline) {
                        _failure = WebViewFailure.none;
                      }
                      _progress = 0;
                    });
                  }
                },
                onProgressChanged: (controller, progress) {
                  if (progress == 100) {
                    unawaited(_pullToRefreshController?.endRefreshing());
                  }
                  if (mounted) {
                    setState(() => _progress = progress);
                  }
                },
                onLoadStop: (controller, url) {
                  unawaited(_pullToRefreshController?.endRefreshing());
                  if (mounted) {
                    setState(() {
                      _progress = 100;
                      _initialLoadComplete = true;
                    });
                  }
                },
                onReceivedError: (controller, request, error) {
                  if (request.isForMainFrame == true && mounted) {
                    setState(() {
                      _failure = webViewFailureForLoadError(
                        connectivityOffline: _connectivityOffline,
                        webViewReportedOffline:
                            error.type ==
                            WebResourceErrorType.NOT_CONNECTED_TO_INTERNET,
                      );
                      _initialLoadComplete = true;
                    });
                  }
                },
                onReceivedHttpError: (controller, request, response) {
                  if (request.isForMainFrame == true &&
                      (response.statusCode ?? 0) >= 500 &&
                      mounted) {
                    setState(() {
                      _failure = WebViewFailure.server;
                      _initialLoadComplete = true;
                    });
                  }
                },
              ),
              if (_progress < 100 && _failure == WebViewFailure.none)
                LinearProgressIndicator(
                  value: _progress == 0 ? null : _progress / 100,
                  color: const Color(0xFFE6B44A),
                  backgroundColor: const Color(0xFF12372A),
                ),
              if (!_initialLoadComplete && _failure == WebViewFailure.none)
                const ColoredBox(
                  color: Color(0xFF12372A),
                  child: Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.spa_outlined,
                          color: Color(0xFFE6B44A),
                          size: 76,
                        ),
                        SizedBox(height: 24),
                        Text(
                          'OYSTER MUSHROOM',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 25,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.5,
                          ),
                        ),
                        SizedBox(height: 8),
                        Text(
                          'Business Manager',
                          style: TextStyle(
                            color: Color(0xFFE6B44A),
                            fontSize: 17,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              if (_downloading)
                const Positioned(
                  top: 8,
                  right: 8,
                  child: Card(
                    child: Padding(
                      padding: EdgeInsets.all(12),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          ),
                          SizedBox(width: 10),
                          Text('Downloading…'),
                        ],
                      ),
                    ),
                  ),
                ),
              if (errorMessage != null)
                ColoredBox(
                  color: Theme.of(context).colorScheme.surface,
                  child: Center(
                    child: Padding(
                      padding: const EdgeInsets.all(32),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            _failure == WebViewFailure.offline
                                ? Icons.wifi_off
                                : Icons.cloud_off,
                            size: 64,
                          ),
                          const SizedBox(height: 20),
                          Text(
                            errorMessage.title,
                            style: Theme.of(context).textTheme.headlineSmall,
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: 8),
                          Text(
                            errorMessage.detail,
                            textAlign: TextAlign.center,
                          ),
                          const SizedBox(height: 24),
                          FilledButton.icon(
                            onPressed: _retry,
                            icon: const Icon(Icons.refresh),
                            label: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
