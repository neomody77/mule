/// Stub for dart:html when not on web platform
/// This allows conditional imports to work

class Window {
  Location get location => Location();
}

class Location {
  String get protocol => '';
  String get hostname => '';
  String get port => '';
  String get href => '';
}

Window get window => Window();
