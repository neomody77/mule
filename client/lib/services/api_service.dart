import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import '../config/app_config.dart';
import '../models/server_config.dart';
import '../models/workspace.dart';
import '../models/file_node.dart';
import 'clerk_auth_service.dart';

/// Token 获取回调类型
typedef TokenGetter = Future<String?> Function();

/// API 服务
class ApiService {
  late final Dio _dio;

  /// 自定义 token 获取器（用于 Clerk 模式）
  TokenGetter? _tokenGetter;

  ApiService({TokenGetter? tokenGetter}) : _tokenGetter = tokenGetter {
    _dio = Dio(BaseOptions(
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 30),
    ));

    // 添加认证拦截器
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        debugPrint('[ApiService] Request: ${options.method} ${options.uri}');

        // 获取 token
        String? token;
        if (!options.headers.containsKey('Authorization')) {
          token = await _getToken();
          if (token != null) {
            options.headers['Authorization'] = 'Bearer $token';
            options.headers['X-API-Token'] = token;
          }
        }

        return handler.next(options);
      },
      onResponse: (response, handler) {
        debugPrint('[ApiService] Response: ${response.statusCode}');
        return handler.next(response);
      },
      onError: (error, handler) {
        debugPrint('[ApiService] Error: ${error.message}');
        return handler.next(error);
      },
    ));
  }

  /// 设置 token 获取器
  void setTokenGetter(TokenGetter getter) {
    _tokenGetter = getter;
  }

  /// 获取当前有效的 token
  Future<String?> _getToken() async {
    // 优先使用自定义 token 获取器
    if (_tokenGetter != null) {
      return await _tokenGetter!();
    }

    // Clerk 模式：从 ClerkAuthService 获取
    if (AppConfig.useClerkAuth) {
      return await ClerkAuthService.instance.getSessionToken();
    }

    // Token 模式：使用静态 token
    return AppConfig.apiToken;
  }

  String get _baseUrl => AppConfig.httpBaseUrl;

  /// 健康检查
  Future<bool> healthCheck() async {
    try {
      final response = await _dio.get('$_baseUrl/health');
      return response.data['status'] == 'healthy';
    } catch (e) {
      return false;
    }
  }

  /// 获取服务器信息
  Future<Map<String, dynamic>> getServerInfo() async {
    final response = await _dio.get('$_baseUrl/');
    return response.data;
  }

  // ==================== 工作区 API ====================

  /// 列出所有工作区
  Future<List<Workspace>> listWorkspaces() async {
    final response = await _dio.get('$_baseUrl/api/workspaces');
    final List<dynamic> data = response.data;
    return data.map((json) => Workspace.fromJson(json)).toList();
  }

  /// 创建工作区
  Future<Workspace> createWorkspace({
    required String name,
    String? description,
  }) async {
    final response = await _dio.post(
      '$_baseUrl/api/workspaces',
      data: {
        'name': name,
        'description': description,
      },
    );
    return Workspace.fromJson(response.data);
  }

  /// 获取工作区详情
  Future<Workspace> getWorkspace(String workspaceId) async {
    final response = await _dio.get('$_baseUrl/api/workspaces/$workspaceId');
    return Workspace.fromJson(response.data);
  }

  /// 删除工作区（软删除）
  Future<void> deleteWorkspace(String workspaceId, {bool permanent = false}) async {
    await _dio.delete(
      '$_baseUrl/api/workspaces/$workspaceId',
      queryParameters: {'permanent': permanent},
    );
  }

  /// 列出回收站（冥府）
  Future<List<Workspace>> listTrash() async {
    final response = await _dio.get('$_baseUrl/api/workspaces/trash/list');
    final List<dynamic> data = response.data;
    return data.map((json) => Workspace.fromJson(json)).toList();
  }

  /// 恢复工作区（还魂）
  Future<Workspace> restoreWorkspace(String workspaceId) async {
    final response = await _dio.post('$_baseUrl/api/workspaces/$workspaceId/restore');
    return Workspace.fromJson(response.data);
  }

  // ==================== 文件 API ====================

  /// 列出工作区文件
  Future<List<FileNode>> listFiles(String workspaceId, {String path = ''}) async {
    final response = await _dio.get(
      '$_baseUrl/api/workspaces/$workspaceId/files',
      queryParameters: {'path': path},
    );
    final List<dynamic> files = response.data['files'];
    return files.map((json) => FileNode.fromJson(json)).toList();
  }

  /// 读取文件内容
  Future<String> readFile(String workspaceId, String filePath) async {
    final response = await _dio.get(
      '$_baseUrl/api/workspaces/$workspaceId/files/$filePath',
    );
    return response.data['content'];
  }

  /// 列出工作区文件（使用指定服务器配置）
  Future<List<FileNode>> listFilesWithServer(
    ServerConfig server,
    String workspaceId, {
    String path = '',
  }) async {
    final response = await _dio.get(
      '${server.httpBaseUrl}/api/workspaces/$workspaceId/files',
      queryParameters: {'path': path},
      options: Options(
        headers: {
          'Authorization': 'Bearer ${server.token}',
          'X-API-Token': server.token,
        },
      ),
    );
    final List<dynamic> files = response.data['files'];
    return files.map((json) => FileNode.fromJson(json)).toList();
  }

  /// 读取文件内容（使用指定服务器配置）
  Future<String> readFileWithServer(
    ServerConfig server,
    String workspaceId,
    String filePath,
  ) async {
    final response = await _dio.get(
      '${server.httpBaseUrl}/api/workspaces/$workspaceId/files/$filePath',
      options: Options(
        headers: {
          'Authorization': 'Bearer ${server.token}',
          'X-API-Token': server.token,
        },
      ),
    );
    return response.data['content'];
  }

  // ==================== Session API ====================

  /// 列出工作区下的所有 sessions
  Future<List<Map<String, dynamic>>> listSessions(String workspaceId) async {
    final response = await _dio.get(
      '$_baseUrl/api/workspaces/$workspaceId/sessions',
    );
    final List<dynamic> sessions = response.data;
    return sessions.cast<Map<String, dynamic>>();
  }

  /// 创建新 session
  Future<Map<String, dynamic>> createSession(
    String workspaceId, {
    String? title,
  }) async {
    final response = await _dio.post(
      '$_baseUrl/api/workspaces/$workspaceId/sessions',
      data: {'title': title},
    );
    return response.data;
  }

  /// 获取 session 详情
  Future<Map<String, dynamic>> getSession(
    String workspaceId,
    String sessionId,
  ) async {
    final response = await _dio.get(
      '$_baseUrl/api/workspaces/$workspaceId/sessions/$sessionId',
    );
    return response.data;
  }

  /// 更新 session
  Future<Map<String, dynamic>> updateSession(
    String workspaceId,
    String sessionId, {
    String? title,
  }) async {
    final response = await _dio.patch(
      '$_baseUrl/api/workspaces/$workspaceId/sessions/$sessionId',
      data: {'title': title},
    );
    return response.data;
  }

  /// 删除 session
  Future<void> deleteSession(String workspaceId, String sessionId) async {
    await _dio.delete(
      '$_baseUrl/api/workspaces/$workspaceId/sessions/$sessionId',
    );
  }

  // ==================== Session 消息 API ====================

  /// 获取 session 消息历史
  Future<List<Map<String, dynamic>>> getSessionMessages(
    String workspaceId,
    String sessionId, {
    int? limit,
    int offset = 0,
  }) async {
    final response = await _dio.get(
      '$_baseUrl/api/workspaces/$workspaceId/sessions/$sessionId/messages',
      queryParameters: {
        if (limit != null) 'limit': limit,
        'offset': offset,
      },
    );
    final List<dynamic> messages = response.data['messages'];
    return messages.cast<Map<String, dynamic>>();
  }

  /// 清空 session 消息历史
  Future<void> clearSessionMessages(String workspaceId, String sessionId) async {
    await _dio.delete(
      '$_baseUrl/api/workspaces/$workspaceId/sessions/$sessionId/messages',
    );
  }
}
