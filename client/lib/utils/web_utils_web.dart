import 'dart:js_interop';
import 'package:web/web.dart' as web;

/// Clear browser cache (Service Worker and Cache Storage)
Future<void> clearBrowserCache() async {
  // Unregister all service workers
  final registrations =
      await web.window.navigator.serviceWorker.getRegistrations().toDart;
  for (final registration in registrations.toDart) {
    await registration.unregister().toDart;
  }

  // Clear all caches
  final cacheNames = await web.window.caches.keys().toDart;
  for (final name in cacheNames.toDart) {
    await web.window.caches.delete(name.toDart).toDart;
  }
}

/// Reload the current page
void reloadPage() {
  web.window.location.reload();
}

/// Get current URL info for default server config
({String name, String host, int port, bool useHttps})? getUrlDefaults() {
  try {
    final location = web.window.location;
    final protocol = location.protocol;
    final hostname = location.hostname;
    final portStr = location.port;

    if (hostname.isEmpty) return null;

    // Parse port
    int port = 8080;
    if (portStr.isNotEmpty) {
      port = int.tryParse(portStr) ?? 8080;
    } else {
      port = protocol == 'https:' ? 443 : 80;
    }

    final useHttps = protocol == 'https:';

    // Generate server name from hostname
    String name = hostname;
    if (hostname.contains('.')) {
      name = hostname.split('.').first;
    }
    if (name.isNotEmpty) {
      name = name[0].toUpperCase() + name.substring(1);
    }

    return (name: name, host: hostname, port: port, useHttps: useHttps);
  } catch (e) {
    return null;
  }
}
