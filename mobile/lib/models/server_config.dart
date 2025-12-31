import 'dart:convert';

/// 服务器配置模型
class ServerConfig {
  final String id;
  final String name;
  final String host;
  final int port;
  final String token;
  final bool useHttps;

  ServerConfig({
    required this.id,
    required this.name,
    required this.host,
    this.port = 8000,
    required this.token,
    this.useHttps = false,
  });

  /// 获取完整的服务器地址
  String get address => '$host:$port';

  /// 获取 HTTP 基础 URL
  String get httpBaseUrl {
    final protocol = useHttps ? 'https' : 'http';
    return '$protocol://$address';
  }

  /// 获取 WebSocket 基础 URL
  String get wsBaseUrl {
    final protocol = useHttps ? 'wss' : 'ws';
    return '$protocol://$address';
  }

  /// 获取工作区的 WebSocket URL
  String getWsUrl(String workspaceId, String sessionId) {
    return '$wsBaseUrl/ws/$workspaceId/$sessionId?token=$token';
  }

  /// 从 JSON 创建
  factory ServerConfig.fromJson(Map<String, dynamic> json) {
    return ServerConfig(
      id: json['id'] as String,
      name: json['name'] as String,
      host: json['host'] as String,
      port: json['port'] as int? ?? 8000,
      token: json['token'] as String,
      useHttps: json['useHttps'] as bool? ?? false,
    );
  }

  /// 转为 JSON
  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'name': name,
      'host': host,
      'port': port,
      'token': token,
      'useHttps': useHttps,
    };
  }

  /// 复制并修改
  ServerConfig copyWith({
    String? id,
    String? name,
    String? host,
    int? port,
    String? token,
    bool? useHttps,
  }) {
    return ServerConfig(
      id: id ?? this.id,
      name: name ?? this.name,
      host: host ?? this.host,
      port: port ?? this.port,
      token: token ?? this.token,
      useHttps: useHttps ?? this.useHttps,
    );
  }

  @override
  String toString() => 'ServerConfig($name: $address)';

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is ServerConfig &&
          runtimeType == other.runtimeType &&
          id == other.id;

  @override
  int get hashCode => id.hashCode;
}

/// 服务器列表的 JSON 序列化辅助
class ServerConfigList {
  static String encode(List<ServerConfig> servers) {
    return jsonEncode(servers.map((s) => s.toJson()).toList());
  }

  static List<ServerConfig> decode(String json) {
    final List<dynamic> list = jsonDecode(json);
    return list.map((e) => ServerConfig.fromJson(e)).toList();
  }
}
