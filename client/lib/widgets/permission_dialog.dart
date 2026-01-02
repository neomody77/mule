import 'dart:convert';
import 'package:flutter/material.dart';

import '../config/theme.dart';

/// 权限请求数据
class PermissionRequest {
  final String sessionId;
  final String toolUseId;
  final String toolName;
  final Map<String, dynamic> toolInput;
  final DateTime requestedAt;

  PermissionRequest({
    required this.sessionId,
    required this.toolUseId,
    required this.toolName,
    required this.toolInput,
    DateTime? requestedAt,
  }) : requestedAt = requestedAt ?? DateTime.now();

  factory PermissionRequest.fromJson(Map<String, dynamic> json) {
    return PermissionRequest(
      sessionId: json['session_id'] as String? ?? '',
      toolUseId: json['tool_use_id'] as String? ?? '',
      toolName: json['tool_name'] as String? ?? 'Unknown',
      toolInput: json['tool_input'] as Map<String, dynamic>? ?? {},
    );
  }
}

/// 权限响应
class PermissionResponse {
  final String behavior; // 'allow', 'deny'
  final Map<String, dynamic>? updatedInput;

  PermissionResponse({
    required this.behavior,
    this.updatedInput,
  });

  Map<String, dynamic> toJson() => {
    'behavior': behavior,
    if (updatedInput != null) 'updatedInput': updatedInput,
  };
}

/// 权限审批对话框
class PermissionApprovalDialog extends StatefulWidget {
  final PermissionRequest request;
  final void Function(PermissionResponse response) onRespond;

  const PermissionApprovalDialog({
    super.key,
    required this.request,
    required this.onRespond,
  });

  static Future<PermissionResponse?> show(
    BuildContext context,
    PermissionRequest request,
  ) async {
    return showDialog<PermissionResponse>(
      context: context,
      barrierDismissible: false,
      builder: (context) => PermissionApprovalDialog(
        request: request,
        onRespond: (response) => Navigator.of(context).pop(response),
      ),
    );
  }

  @override
  State<PermissionApprovalDialog> createState() =>
      _PermissionApprovalDialogState();
}

class _PermissionApprovalDialogState extends State<PermissionApprovalDialog> {
  bool _showDetails = false;

  String get _toolDescription {
    switch (widget.request.toolName) {
      case 'Bash':
        return 'Execute shell command';
      case 'Read':
        return 'Read file contents';
      case 'Write':
        return 'Write to file';
      case 'Edit':
        return 'Edit file contents';
      case 'Glob':
        return 'Search for files';
      case 'Grep':
        return 'Search in file contents';
      case 'WebFetch':
        return 'Fetch URL content';
      case 'WebSearch':
        return 'Search the web';
      default:
        return 'Use tool: ${widget.request.toolName}';
    }
  }

  Widget _buildToolIcon() {
    IconData icon;
    Color color;

    switch (widget.request.toolName) {
      case 'Bash':
        icon = Icons.terminal;
        color = Colors.orange;
        break;
      case 'Read':
        icon = Icons.description;
        color = ZiaOlive.shade500;
        break;
      case 'Write':
        icon = Icons.edit_document;
        color = Colors.blue;
        break;
      case 'Edit':
        icon = Icons.edit;
        color = Colors.purple;
        break;
      case 'Glob':
        icon = Icons.folder_open;
        color = Colors.teal;
        break;
      case 'Grep':
        icon = Icons.search;
        color = Colors.indigo;
        break;
      case 'WebFetch':
      case 'WebSearch':
        icon = Icons.public;
        color = Colors.green;
        break;
      default:
        icon = Icons.extension;
        color = ZiaOlive.shade400;
    }

    return Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Icon(icon, color: color, size: 24),
    );
  }

  String _getMainParameter() {
    final input = widget.request.toolInput;

    switch (widget.request.toolName) {
      case 'Bash':
        return input['command'] as String? ?? '';
      case 'Read':
      case 'Write':
      case 'Edit':
        return input['file_path'] as String? ?? '';
      case 'Glob':
        return input['pattern'] as String? ?? '';
      case 'Grep':
        return input['pattern'] as String? ?? '';
      case 'WebFetch':
      case 'WebSearch':
        return input['url'] as String? ?? input['query'] as String? ?? '';
      default:
        return jsonEncode(input);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.security, color: Colors.orange),
          const SizedBox(width: 12),
          const Expanded(
            child: Text('Permission Required'),
          ),
        ],
      ),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 工具信息
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildToolIcon(),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.request.toolName,
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 16,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        _toolDescription,
                        style: TextStyle(
                          color: ZiaOlive.shade300,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),

            const SizedBox(height: 16),
            const Divider(),
            const SizedBox(height: 12),

            // 主要参数
            Text(
              _getMainParameter(),
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 13,
              ),
              maxLines: _showDetails ? 20 : 3,
              overflow: TextOverflow.ellipsis,
            ),

            // 展开/收起详情
            if (widget.request.toolInput.length > 1 ||
                _getMainParameter().length > 100)
              TextButton(
                onPressed: () => setState(() => _showDetails = !_showDetails),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(_showDetails ? 'Hide details' : 'Show details'),
                    Icon(
                      _showDetails
                          ? Icons.keyboard_arrow_up
                          : Icons.keyboard_arrow_down,
                      size: 18,
                    ),
                  ],
                ),
              ),

            // 详细参数
            if (_showDetails) ...[
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: ZiaOlive.shade100,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  const JsonEncoder.withIndent('  ')
                      .convert(widget.request.toolInput),
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                  ),
                ),
              ),
            ],

            const SizedBox(height: 16),

            // 会话信息
            Row(
              children: [
                Icon(Icons.terminal, size: 14, color: ZiaOlive.shade300),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    'Session: ${widget.request.sessionId.length > 16 ? '${widget.request.sessionId.substring(0, 16)}...' : widget.request.sessionId}',
                    style: TextStyle(
                      fontSize: 11,
                      color: ZiaOlive.shade300,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      actions: [
        // 拒绝按钮
        OutlinedButton(
          onPressed: () {
            widget.onRespond(PermissionResponse(behavior: 'deny'));
          },
          style: OutlinedButton.styleFrom(
            foregroundColor: ZiaOlive.error,
          ),
          child: const Text('Deny'),
        ),
        // 允许按钮
        FilledButton(
          onPressed: () {
            widget.onRespond(PermissionResponse(behavior: 'allow'));
          },
          child: const Text('Allow'),
        ),
      ],
    );
  }
}

/// 权限请求通知横幅（非阻塞式）
class PermissionRequestBanner extends StatelessWidget {
  final PermissionRequest request;
  final VoidCallback onAllow;
  final VoidCallback onDeny;
  final VoidCallback onViewDetails;

  const PermissionRequestBanner({
    super.key,
    required this.request,
    required this.onAllow,
    required this.onDeny,
    required this.onViewDetails,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      elevation: 4,
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.orange.withValues(alpha: 0.1),
          border: Border(
            left: BorderSide(color: Colors.orange, width: 4),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Icon(Icons.security, color: Colors.orange, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Permission Required',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 13,
                        ),
                      ),
                      Text(
                        '${request.toolName}: ${_getShortDescription()}',
                        style: TextStyle(
                          fontSize: 12,
                          color: ZiaOlive.shade400,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
                TextButton(
                  onPressed: onViewDetails,
                  child: const Text('Details'),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                OutlinedButton(
                  onPressed: onDeny,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: ZiaOlive.error,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                  ),
                  child: const Text('Deny'),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: onAllow,
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                  ),
                  child: const Text('Allow'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _getShortDescription() {
    final input = request.toolInput;
    switch (request.toolName) {
      case 'Bash':
        final cmd = input['command'] as String? ?? '';
        return cmd.length > 40 ? '${cmd.substring(0, 40)}...' : cmd;
      case 'Read':
      case 'Write':
      case 'Edit':
        final path = input['file_path'] as String? ?? '';
        final parts = path.split('/');
        return parts.isNotEmpty ? parts.last : path;
      default:
        return jsonEncode(input).substring(
          0,
          40.clamp(0, jsonEncode(input).length),
        );
    }
  }
}
