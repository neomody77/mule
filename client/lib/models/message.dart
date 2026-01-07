import 'dart:typed_data';

import 'package:uuid/uuid.dart';

/// 消息类型
enum MessageType {
  user,
  assistant,
  system,
  toolCall,
  toolResult,
  error,
  status,
}

/// 工具调用信息
class ToolCall {
  final String id;
  final String name;
  final String? description;  // 用户友好的描述，如 "Reading file.py..."
  final Map<String, dynamic>? arguments;
  final Map<String, dynamic>? result;
  final bool isExecuting;

  ToolCall({
    required this.id,
    required this.name,
    this.description,
    this.arguments,
    this.result,
    this.isExecuting = false,
  });

  ToolCall copyWith({
    String? id,
    String? name,
    String? description,
    Map<String, dynamic>? arguments,
    Map<String, dynamic>? result,
    bool? isExecuting,
  }) {
    return ToolCall(
      id: id ?? this.id,
      name: name ?? this.name,
      description: description ?? this.description,
      arguments: arguments ?? this.arguments,
      result: result ?? this.result,
      isExecuting: isExecuting ?? this.isExecuting,
    );
  }
}

/// 聊天消息
class ChatMessage {
  final String id;
  final MessageType type;
  final String content;
  final DateTime timestamp;
  final List<ToolCall> toolCalls;
  final bool isStreaming;
  final bool isPending; // 已发送但尚未被处理
  final Uint8List? imageData; // 图片数据（用于本地显示）

  ChatMessage({
    String? id,
    required this.type,
    this.content = '',
    DateTime? timestamp,
    this.toolCalls = const [],
    this.isStreaming = false,
    this.isPending = false,
    this.imageData,
  })  : id = id ?? const Uuid().v4(),
        timestamp = timestamp ?? DateTime.now();

  /// 是否包含图片
  bool get hasImage => imageData != null && imageData!.isNotEmpty;

  ChatMessage copyWith({
    String? id,
    MessageType? type,
    String? content,
    DateTime? timestamp,
    List<ToolCall>? toolCalls,
    bool? isStreaming,
    bool? isPending,
    Uint8List? imageData,
  }) {
    return ChatMessage(
      id: id ?? this.id,
      type: type ?? this.type,
      content: content ?? this.content,
      timestamp: timestamp ?? this.timestamp,
      toolCalls: toolCalls ?? this.toolCalls,
      isStreaming: isStreaming ?? this.isStreaming,
      isPending: isPending ?? this.isPending,
      imageData: imageData ?? this.imageData,
    );
  }

  /// 追加文本内容
  ChatMessage appendContent(String text) {
    return copyWith(content: content + text);
  }

  /// 添加工具调用
  ChatMessage addToolCall(ToolCall toolCall) {
    return copyWith(toolCalls: [...toolCalls, toolCall]);
  }

  /// 更新工具调用
  ChatMessage updateToolCall(String toolId, ToolCall Function(ToolCall) update) {
    final updatedCalls = toolCalls.map((tc) {
      if (tc.id == toolId) {
        return update(tc);
      }
      return tc;
    }).toList();
    return copyWith(toolCalls: updatedCalls);
  }
}
