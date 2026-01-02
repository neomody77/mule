import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';

import '../models/server_config.dart';

/// 自动连接参数
class ConnectParams {
  final String host;
  final int port;
  final String token;
  final String name;
  final bool https;

  ConnectParams({
    required this.host,
    required this.port,
    required this.token,
    required this.name,
    required this.https,
  });

  factory ConnectParams.fromJson(Map<String, dynamic> json) {
    return ConnectParams(
      host: json['host'] as String,
      port: json['port'] as int,
      token: json['token'] as String,
      name: json['name'] as String? ?? 'Mule Server',
      https: json['https'] as bool? ?? false,
    );
  }

  /// 转换为 ServerConfig
  ServerConfig toServerConfig() {
    return ServerConfig(
      id: const Uuid().v4(),
      name: name,
      host: host,
      port: port,
      token: token,
      useHttps: https,
    );
  }
}

/// 自动连接服务
class AutoConnectService {
  static final AutoConnectService instance = AutoConnectService._();

  AutoConnectService._();

  /// 从 URL 中获取加密的连接参数
  String? getEncryptedParamFromUrl() {
    if (!kIsWeb) return null;

    try {
      final uri = Uri.base;
      return uri.queryParameters['c'];
    } catch (e) {
      debugPrint('[AutoConnect] Failed to parse URL: $e');
      return null;
    }
  }

  /// 解密连接参数
  /// 需要向服务器发送请求来解密（因为密钥在服务端）
  Future<ConnectParams?> decryptConnectParams(String encrypted) async {
    // 首先需要确定目标服务器
    // 加密参数中包含了 host:port，我们需要从当前页面 URL 推断
    if (!kIsWeb) return null;

    try {
      final uri = Uri.base;
      final host = uri.host;
      final port = uri.port;
      final scheme = uri.scheme;

      // 构建解密 API URL
      final apiUrl = '$scheme://$host:$port/api/connect/decrypt?c=$encrypted';

      debugPrint('[AutoConnect] Decrypting via: $apiUrl');

      final response = await http.get(Uri.parse(apiUrl)).timeout(
        const Duration(seconds: 10),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);

        if (data.containsKey('error')) {
          debugPrint('[AutoConnect] Decrypt error: ${data['error']}');
          return null;
        }

        return ConnectParams.fromJson(data);
      } else {
        debugPrint('[AutoConnect] Decrypt failed: ${response.statusCode}');
        return null;
      }
    } catch (e) {
      debugPrint('[AutoConnect] Decrypt exception: $e');
      return null;
    }
  }

  /// 检查并处理 URL 中的自动连接参数
  Future<ServerConfig?> checkAndProcessAutoConnect() async {
    final encrypted = getEncryptedParamFromUrl();
    if (encrypted == null) {
      debugPrint('[AutoConnect] No connect param in URL');
      return null;
    }

    debugPrint('[AutoConnect] Found encrypted param: ${encrypted.substring(0, 20)}...');

    final params = await decryptConnectParams(encrypted);
    if (params == null) {
      debugPrint('[AutoConnect] Failed to decrypt params');
      return null;
    }

    debugPrint('[AutoConnect] Decrypted: ${params.name} @ ${params.host}:${params.port}');

    return params.toServerConfig();
  }
}
