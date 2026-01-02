import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:uuid/uuid.dart';
import 'package:http/http.dart' as http;

import '../models/server_config.dart';
import '../models/workspace.dart';

/// 服务器状态
class ServerState {
  final List<ServerConfig> servers;
  final Map<String, List<WorkspaceInfo>> workspaces; // serverId -> workspaces
  final Map<String, bool> serverStatus; // serverId -> isOnline
  final bool isLoading;

  const ServerState({
    this.servers = const [],
    this.workspaces = const {},
    this.serverStatus = const {},
    this.isLoading = false,
  });

  ServerState copyWith({
    List<ServerConfig>? servers,
    Map<String, List<WorkspaceInfo>>? workspaces,
    Map<String, bool>? serverStatus,
    bool? isLoading,
  }) {
    return ServerState(
      servers: servers ?? this.servers,
      workspaces: workspaces ?? this.workspaces,
      serverStatus: serverStatus ?? this.serverStatus,
      isLoading: isLoading ?? this.isLoading,
    );
  }

  List<WorkspaceInfo> getWorkspaces(String serverId) {
    return workspaces[serverId] ?? [];
  }

  bool isServerOnline(String serverId) {
    return serverStatus[serverId] ?? false;
  }

  ServerConfig? getServer(String serverId) {
    try {
      return servers.firstWhere((s) => s.id == serverId);
    } catch (_) {
      return null;
    }
  }
}

/// 服务器 Notifier
class ServerNotifier extends StateNotifier<ServerState> {
  static const String _storageKey = 'mule_servers';

  ServerNotifier() : super(const ServerState());

  /// 加载保存的服务器配置
  Future<void> load() async {
    debugPrint('[ServerNotifier] load() called');
    state = state.copyWith(isLoading: true);
    try {
      final prefs = await SharedPreferences.getInstance();
      final json = prefs.getString(_storageKey);
      debugPrint('[ServerNotifier] load() json: ${json != null ? "${json.length} chars" : "null"}');
      if (json != null) {
        final servers = ServerConfigList.decode(json);
        debugPrint('[ServerNotifier] load() decoded ${servers.length} servers');
        state = state.copyWith(servers: servers, isLoading: false);
        // 刷新所有服务器状态
        await refreshAllServers();
      } else {
        state = state.copyWith(isLoading: false);
      }
    } catch (e) {
      debugPrint('[ServerNotifier] load() error: $e');
      state = state.copyWith(isLoading: false);
    }
  }

  /// 保存服务器配置
  Future<void> _save() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_storageKey, ServerConfigList.encode(state.servers));
    } catch (e) {
      // ignore
    }
  }

  /// 添加服务器
  Future<ServerConfig> addServer({
    required String name,
    required String host,
    required int port,
    required String token,
    bool useHttps = false,
  }) async {
    final server = ServerConfig(
      id: const Uuid().v4(),
      name: name,
      host: host,
      port: port,
      token: token,
      useHttps: useHttps,
    );

    state = state.copyWith(servers: [...state.servers, server]);
    await _save();

    // 立即检查连接状态
    await refreshServer(server.id);

    return server;
  }

  /// 更新服务器配置
  Future<void> updateServer(ServerConfig server) async {
    final index = state.servers.indexWhere((s) => s.id == server.id);
    if (index >= 0) {
      final newServers = [...state.servers];
      newServers[index] = server;
      state = state.copyWith(servers: newServers);
      await _save();
      await refreshServer(server.id);
    }
  }

  /// 删除服务器
  Future<void> deleteServer(String serverId) async {
    final newServers = state.servers.where((s) => s.id != serverId).toList();
    final newWorkspaces = Map<String, List<WorkspaceInfo>>.from(state.workspaces)
      ..remove(serverId);
    final newStatus = Map<String, bool>.from(state.serverStatus)..remove(serverId);

    state = state.copyWith(
      servers: newServers,
      workspaces: newWorkspaces,
      serverStatus: newStatus,
    );
    await _save();
  }

  /// 刷新所有服务器，返回所有在线服务器及其 workspaces
  Future<Map<ServerConfig, List<WorkspaceInfo>>> refreshAllServers() async {
    debugPrint('[ServerNotifier] refreshAllServers: ${state.servers.length} servers');
    final results = <ServerConfig, List<WorkspaceInfo>>{};

    await Future.wait(state.servers.map((server) async {
      debugPrint('[ServerNotifier] Refreshing server: ${server.name}');
      final workspaces = await refreshServer(server.id);
      debugPrint('[ServerNotifier] Server ${server.name}: ${workspaces.length} workspaces');
      if (workspaces.isNotEmpty) {
        results[server] = workspaces;
      }
    }));

    debugPrint('[ServerNotifier] refreshAllServers done: ${results.length} online servers');
    return results;
  }

  /// 刷新指定服务器，返回 workspaces 列表
  Future<List<WorkspaceInfo>> refreshServer(String serverId) async {
    final server = state.getServer(serverId);
    if (server == null) return [];

    try {
      final workspaces = await _fetchWorkspaces(server);
      final newWorkspaces = Map<String, List<WorkspaceInfo>>.from(state.workspaces)
        ..[serverId] = workspaces;
      final newStatus = Map<String, bool>.from(state.serverStatus)
        ..[serverId] = true;

      state = state.copyWith(workspaces: newWorkspaces, serverStatus: newStatus);
      return workspaces;
    } catch (e) {
      final newStatus = Map<String, bool>.from(state.serverStatus)
        ..[serverId] = false;
      final newWorkspaces = Map<String, List<WorkspaceInfo>>.from(state.workspaces)
        ..[serverId] = [];

      state = state.copyWith(workspaces: newWorkspaces, serverStatus: newStatus);
      return [];
    }
  }

  /// 获取服务器的工作区列表
  Future<List<WorkspaceInfo>> _fetchWorkspaces(ServerConfig server) async {
    final url = '${server.httpBaseUrl}/api/workspaces';
    final response = await http.get(
      Uri.parse(url),
      headers: {'Authorization': 'Bearer ${server.token}'},
    ).timeout(const Duration(seconds: 10));

    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data.map((e) => WorkspaceInfo.fromJson(e)).toList();
    } else {
      throw Exception('Failed to fetch workspaces: ${response.statusCode}');
    }
  }

  /// 创建工作区
  Future<WorkspaceInfo?> createWorkspace(
    String serverId, {
    required String name,
    String? description,
  }) async {
    final server = state.getServer(serverId);
    if (server == null) return null;

    try {
      final url = '${server.httpBaseUrl}/api/workspaces';
      final response = await http.post(
        Uri.parse(url),
        headers: {
          'Authorization': 'Bearer ${server.token}',
          'Content-Type': 'application/json',
        },
        body: jsonEncode({
          'name': name,
          if (description != null) 'description': description,
        }),
      );

      if (response.statusCode == 201) {
        final workspace = WorkspaceInfo.fromJson(jsonDecode(response.body));
        await refreshServer(serverId);
        return workspace;
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  /// 删除工作区
  Future<bool> deleteWorkspace(
    String serverId,
    String workspaceId, {
    bool permanent = false,
  }) async {
    final server = state.getServer(serverId);
    if (server == null) return false;

    try {
      final url =
          '${server.httpBaseUrl}/api/workspaces/$workspaceId?permanent=$permanent';
      final response = await http.delete(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer ${server.token}'},
      );

      if (response.statusCode == 204) {
        await refreshServer(serverId);
        return true;
      }
      return false;
    } catch (e) {
      return false;
    }
  }
}

/// 服务器 Provider
final serverProvider = StateNotifierProvider<ServerNotifier, ServerState>((ref) {
  final notifier = ServerNotifier();
  notifier.load(); // 自动加载
  return notifier;
});
