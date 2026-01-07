import 'package:flutter/foundation.dart' show kIsWeb;

// Conditional import for web platform
import 'web_utils_stub.dart' if (dart.library.js_interop) 'web_utils_web.dart'
    as platform;

/// Clear browser cache (Service Worker and Cache Storage)
Future<void> clearBrowserCache() async {
  if (!kIsWeb) return;
  await platform.clearBrowserCache();
}

/// Reload the current page
void reloadPage() {
  if (!kIsWeb) return;
  platform.reloadPage();
}

/// Get current URL info for default server config
({String name, String host, int port, bool useHttps})? getUrlDefaults() {
  if (!kIsWeb) return null;
  return platform.getUrlDefaults();
}
