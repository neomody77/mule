import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../config/theme.dart';
import '../models/server_config.dart';
import '../router.dart';
import '../services/api_service.dart';

/// 文件查看器页面
class FileViewerScreen extends ConsumerStatefulWidget {
  final ServerConfig server;
  final String workspaceId;
  final String filePath;
  final String fileName;

  const FileViewerScreen({
    super.key,
    required this.server,
    required this.workspaceId,
    required this.filePath,
    required this.fileName,
  });

  @override
  ConsumerState<FileViewerScreen> createState() => _FileViewerScreenState();
}

class _FileViewerScreenState extends ConsumerState<FileViewerScreen> {
  final ApiService _api = ApiService();

  String? _content;
  bool _isLoading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadContent();
  }

  Future<void> _loadContent() async {
    setState(() {
      _isLoading = true;
      _error = null;
    });

    try {
      final content = await _api.readFileWithServer(
        widget.server,
        widget.workspaceId,
        widget.filePath,
      );
      setState(() {
        _content = content;
        _isLoading = false;
      });
    } catch (e) {
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  String get _fileExtension {
    final parts = widget.fileName.split('.');
    return parts.length > 1 ? parts.last.toLowerCase() : '';
  }

  bool get _isCode {
    const codeExtensions = {
      'dart', 'py', 'js', 'ts', 'tsx', 'jsx', 'java', 'kt', 'swift',
      'go', 'rs', 'c', 'cpp', 'h', 'hpp', 'cs', 'rb', 'php', 'sh',
      'bash', 'zsh', 'fish', 'ps1', 'sql', 'html', 'css', 'scss',
      'sass', 'less', 'vue', 'svelte',
    };
    return codeExtensions.contains(_fileExtension);
  }

  bool get _isConfig {
    const configExtensions = {
      'json', 'yaml', 'yml', 'toml', 'xml', 'ini', 'conf', 'cfg',
      'properties', 'env', 'lock',
    };
    return configExtensions.contains(_fileExtension);
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.fileName),
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go(AppRoutes.home);
            }
          },
        ),
        actions: [
          // 刷新按钮
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadContent,
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 文件路径信息
          _buildPathInfo(),

          // 文件内容
          Expanded(
            child: _isLoading
                ? const Center(child: CircularProgressIndicator())
                : _error != null
                    ? _buildError()
                    : _buildContent(),
          ),
        ],
      ),
    );
  }

  Widget _buildPathInfo() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final bgColor = isDark ? ZiaOlive.shade800 : ZiaOlive.shade50;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      color: bgColor,
      child: Row(
        children: [
          Icon(
            _getFileIcon(),
            size: 16,
            color: ZiaOlive.shade400,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              widget.filePath,
              style: TextStyle(
                fontSize: 12,
                color: ZiaOlive.shade400,
                fontFamily: 'monospace',
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  IconData _getFileIcon() {
    if (_isCode) return Icons.code;
    if (_isConfig) return Icons.data_object;

    switch (_fileExtension) {
      case 'md':
      case 'txt':
      case 'readme':
        return Icons.description;
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'gif':
      case 'svg':
      case 'webp':
        return Icons.image;
      case 'pdf':
        return Icons.picture_as_pdf;
      default:
        return Icons.insert_drive_file;
    }
  }

  Widget _buildError() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.error_outline, size: 48, color: ZiaOlive.error),
          const SizedBox(height: 16),
          Text(
            'Failed to load file',
            style: TextStyle(
              fontSize: 16,
              color: ZiaOlive.error,
            ),
          ),
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Text(
              _error ?? '',
              style: TextStyle(
                fontSize: 12,
                color: ZiaOlive.shade300,
              ),
              textAlign: TextAlign.center,
            ),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _loadContent,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildContent() {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final content = _content ?? '';

    if (content.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.description_outlined, size: 48, color: ZiaOlive.shade300),
            const SizedBox(height: 16),
            Text(
              'Empty file',
              style: TextStyle(
                fontSize: 16,
                color: ZiaOlive.shade300,
              ),
            ),
          ],
        ),
      );
    }

    // 代码和配置文件使用等宽字体
    final isMonospace = _isCode || _isConfig;
    final lines = content.split('\n');

    return Container(
      color: isDark ? ZiaOlive.shade900 : Colors.white,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(12),
          child: SelectableText.rich(
            TextSpan(
              children: _buildLineNumbers(lines, isMonospace, isDark),
            ),
          ),
        ),
      ),
    );
  }

  List<InlineSpan> _buildLineNumbers(List<String> lines, bool isMonospace, bool isDark) {
    final List<InlineSpan> spans = [];
    final lineNumberWidth = lines.length.toString().length;

    for (var i = 0; i < lines.length; i++) {
      final lineNum = (i + 1).toString().padLeft(lineNumberWidth);

      // 行号
      spans.add(TextSpan(
        text: '$lineNum  ',
        style: TextStyle(
          fontFamily: 'monospace',
          fontSize: 13,
          color: ZiaOlive.shade300,
        ),
      ));

      // 行内容
      spans.add(TextSpan(
        text: '${lines[i]}\n',
        style: TextStyle(
          fontFamily: isMonospace ? 'monospace' : null,
          fontSize: 13,
          color: isDark ? ZiaOlive.shade100 : ZiaOlive.shade700,
          height: 1.5,
        ),
      ));
    }

    return spans;
  }
}
