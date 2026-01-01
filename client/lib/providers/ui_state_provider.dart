import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// UI 状态（展开状态等）
class UIState {
  /// workspace 展开状态 (workspaceKey -> isExpanded)
  /// workspaceKey 格式: "serverId:workspaceId"
  final Map<String, bool> workspaceExpanded;

  const UIState({
    this.workspaceExpanded = const {},
  });

  UIState copyWith({
    Map<String, bool>? workspaceExpanded,
  }) {
    return UIState(
      workspaceExpanded: workspaceExpanded ?? this.workspaceExpanded,
    );
  }

  /// 获取 workspace 是否展开（默认折叠）
  bool isWorkspaceExpanded(String serverId, String workspaceId) {
    final key = '$serverId:$workspaceId';
    return workspaceExpanded[key] ?? false;
  }
}

/// UI 状态 Notifier
class UIStateNotifier extends StateNotifier<UIState> {
  static const String _storageKey = 'mule_ui_state';

  UIStateNotifier() : super(const UIState());

  /// 加载 UI 状态
  Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final json = prefs.getString(_storageKey);
      if (json != null) {
        final data = jsonDecode(json) as Map<String, dynamic>;
        final expanded = (data['workspaceExpanded'] as Map<String, dynamic>?)
            ?.map((k, v) => MapEntry(k, v as bool)) ?? {};
        state = state.copyWith(workspaceExpanded: expanded);
      }
    } catch (e) {
      // ignore
    }
  }

  /// 保存 UI 状态
  Future<void> _save() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final data = {
        'workspaceExpanded': state.workspaceExpanded,
      };
      await prefs.setString(_storageKey, jsonEncode(data));
    } catch (e) {
      // ignore
    }
  }

  /// 切换 workspace 展开状态
  void toggleWorkspaceExpanded(String serverId, String workspaceId) {
    final key = '$serverId:$workspaceId';
    final currentState = state.workspaceExpanded[key] ?? false;
    final newExpanded = Map<String, bool>.from(state.workspaceExpanded)
      ..[key] = !currentState;
    state = state.copyWith(workspaceExpanded: newExpanded);
    _save();
  }

  /// 设置 workspace 展开状态
  void setWorkspaceExpanded(String serverId, String workspaceId, bool expanded) {
    final key = '$serverId:$workspaceId';
    final newExpanded = Map<String, bool>.from(state.workspaceExpanded)
      ..[key] = expanded;
    state = state.copyWith(workspaceExpanded: newExpanded);
    _save();
  }

  /// 全部折叠
  void collapseAll() {
    state = state.copyWith(workspaceExpanded: {});
    _save();
  }

  /// 全部展开
  void expandAll(List<String> workspaceKeys) {
    final newExpanded = {for (var key in workspaceKeys) key: true};
    state = state.copyWith(workspaceExpanded: newExpanded);
    _save();
  }
}

/// UI 状态 Provider
final uiStateProvider = StateNotifierProvider<UIStateNotifier, UIState>((ref) {
  final notifier = UIStateNotifier();
  notifier.load();
  return notifier;
});

/// 便捷 Provider: 获取特定 workspace 的展开状态
final workspaceExpandedProvider = Provider.family<bool, ({String serverId, String workspaceId})>((ref, params) {
  final uiState = ref.watch(uiStateProvider);
  return uiState.isWorkspaceExpanded(params.serverId, params.workspaceId);
});
